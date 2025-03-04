# modification by Philippe F6IFY to use the DJControl Compact midi device
# This script is a modification of the original script from the EESDR project
# by Matthew McDougal, KA0S
# Philippe Nouchi - 9th December 2024
# See the PDF file for the mapping of the DJControl Compact from Hercules

# Version 1.2 Ph. Nouchi - F6IFY le 4 mars 2025
#   - Add the possibility to change the filter width with the button 4
#   - The value of the filter depend of the Hot CUE or Loop button
# Version 1.1 Ph. Nouchi - F6IFY le 28 Février 2025
#   - Include the DJControl Starlight from Hercules
# Version 1.0 Ph. Nouchi - F6IFY le 24 Février 2025
# This version seems stable so I call it 1.0
#   - Add a filtre 2.4khz for SSB contest
# Version 0.4 Ph. Nouchi - F6IFY le 21 Février 2025
#   - Mode of the code for button 2A
#   - Add Split toggle on button 1B
# Version 0.3 Ph. Nouchi - F6IFY le 19 Février 2025
#   - Add Change of the vfoStep variable with button 2A
# Version 0.2 Ph. Nouchi - F6IFY le 12 Février 2025
# Version 0.1 Ph. Nouchi - F6IFY le 15 Janvier 2025


from enum import IntEnum
from functools import partial
from bisect import bisect_right, bisect_left
from urllib.parse import non_hierarchical

from eesdr_tci import tci
from eesdr_tci.listener import Listener
from eesdr_tci.tci import TciCommandSendAction
# from config import Config
import mido
#import rtmidi
import mido.backends.rtmidi
import asyncio

# to help future modification with new midi device
midi_hardware = mido.get_input_names()
midi_port = midi_hardware[0]
print(f"midi device is {midi_port}")

class MIDI(IntEnum):
    KEYUP = 0
    ENCDOWN = 127 # 21
    CLICK = 63 # 63
    ENCUP =  1 # 105
    KEYDOWN = 127

class DJ(IntEnum): # Value for the DJControl compact from hercule
    # ** JOG **
    JOGORPOT = 176
    JOGA = 48
    SHIFTJOGA = 55
    JOGB = 49
    SHIFTJOGB = 56
    # ** *Potentiometres ** *
    POTVOLUMEA = 57
    POTVOLUMEB = 61
    POTMEDIUMA = 59
    POTMEDIUMB = 63
    POTBASSA = 60
    POTBASSB = 64
    # ** *Cross - Fader ** *
    CROSSFADER = 54
    # ** *Buttons ** *
    PUSH_BUTTON = 0 # 144
    BTN_SYNC_A = 35
    BTN_CUE_A = 34
    BTN_PLAY_A = 33
    BTN_SYNC_B = 83
    BTN_CUE_B = 82
    BTN_PLAY_B = 81
    BTN_1A = 1
    BTN_SHIFT1A = 5
    BTN_2A = 2
    BTN_3A = 3
    BTN_4A = 4
    BTN_1B = 49
    BTN_2B = 50
    BTN_3B = 51
    BTN_4B = 52
    BTN_SHIFT1B = 53
    BTN_SHIFT2B = 54
    BTN_SHIFT3B = 55
    BTN_SHIFT4B = 56
    BTN_REC = 43
    BTN_SHIFTREC = 44
    BTN_AUTOMIX = 45
    BTN_SHIFTAUTOMIX = 46
    BTN_MODE = 48
    BTN_SHIFT = 47

class DJS(IntEnum): # Value for the DJControl Starlight from hercule
    # ** JOG **
    JOGORPOT = 176
    JOG = 10
    # ** *Potentiometres ** *
    POTVOLUME1 = 3
    POTVOLUME2 = 4
    POTMEDIUM = 0
    POTBASS = 2
    # ** *Cross - Fader ** *
    CROSSFADER = 0
    # ** *Buttons ** *
    PUSH_BUTTON = 0 # 144
    BTN_SYNC = 5
    BTN_CUE = 6
    BTN_PLAY = 7
    BTN_1 = 0
    BTN_2 = 1
    BTN_3 = 2
    BTN_4 = 3
    BTN_1L = 16
    BTN_2L = 17
    BTN_3L = 18
    BTN_4L = 19
    BTN_BASS_FILTER = 1
    BTN_SHIFT = 3
    BTN_HELMET = 12
    BTN_HOT = 15
    BTN_LOOP = 16

class MODS:
    UI_LIST = ["AM", "LSB", "USB", "CW", "NFM", "DIGL", "DIGU", "WFM"]
    UI_LIST_MAX = len(UI_LIST) - 1
    DEFAULT_LEFT  = {"AM": -3000, "LSB": -3000, "USB":   25, "CW": -250, "NFM": -6000, "DIGL": -3000, "DIGU":   25, "WFM": -24000}
    DEFAULT_RIGHT = {"AM":  3000, "LSB":   -25, "USB": 3000, "CW":  250, "NFM":  6000, "DIGL":   -25, "DIGU": 3000, "WFM":  24000}
    WHEEL_LEFT  = {"AM": -25, "LSB": -25, "USB":  0, "CW": -25, "NFM": -25, "DIGL": -25, "DIGU":  0, "WFM": -250}
    WHEEL_RIGHT = {"AM":  25, "LSB":   0, "USB": 25, "CW":  25, "NFM":  25, "DIGL":   0, "DIGU": 25, "WFM":  250}

# class KNOBPLANE(IntEnum):
#     BASE = 0
#     FILTER = 1
#     MOD = 2
#     BAND = 3
#     DRIVE = 4
#     VOLUME = 5
#     MONITOR = 6

class FILTERSIDE(IntEnum):
    LEFT  = -1
    MAIN  =  0
    RIGHT =  1

class Band:
    def __init__(self, name, min_freq, max_freq, seg1=None, seg2=None):
        self.name = name
        self.min_freq = min_freq * 1000
        self.max_freq = max_freq * 1000
        if seg1 is None:
            self.seg1_freq = (self.min_freq + self.max_freq) / 2
            self.seg2_freq = None
        else:
            self.seg1_freq = seg1 * 1000

        if seg2 is None:
            self.seg2_freq = None
        else:
            self.seg2_freq = seg2 * 1000

    def in_band(self, freq):
        return freq >= self.min_freq and freq <= self.max_freq

    def points(self):
        if self.seg2_freq == None:
            return [self.seg1_freq]
        else:
            return [self.seg1_freq, self.seg2_freq]

class BANDS:
    INFO = [ Band("160m", 1800, 2000), 
             Band("80m", 3500, 4000, 3525, 3800), 
             Band("60m", 5330.5, 5407.5, 5358.5), 
             Band("40m", 7000, 7300, 7025, 7175),
             Band("30m", 10100, 10150),
             Band("20m", 14000, 14350, 14025, 14225),
             Band("17m", 18068, 18168, 18110),
             Band("15m", 21000, 21450, 21025, 21275),
             Band("12m", 24890, 24990, 24930),
             Band("10m", 28000, 29700, 28300, 29000),
             Band("6m", 50000, 54000, 50100, 52000),
             Band("2m", 144000, 148000, 144100, 147000),
           ]
    NAMES = [band.name for band in INFO]
    POINTS = [i for j in [band.points() for band in INFO] for i in j]

    def FreqBand(freq):
        chk = [band.in_band(freq) for band in BANDS.INFO]
        if not any(chk):
            return None
        else:
            return BANDS.INFO[chk.index(True)]

params_dict = {}

async def update_params(name, rx, subrx, params):
    global params_dict
    # print("TCI", name, rx, subrx, params)
    if rx not in params_dict:
        params_dict[rx] = {}
    if subrx not in params_dict[rx]:
        params_dict[rx][subrx] = {}
    params_dict[rx][subrx][name] = params

def get_param(name, rx = None, subrx = None):
    global params_dict
    cmd = tci.COMMANDS[name]
    if not cmd.has_rx:
        rx = None
    if not cmd.has_sub_rx:
        subrx = None
    return params_dict[rx][subrx][name]

def do_band_scroll(val, rx, subrx):
    rx_dds = get_param("DDS", rx, subrx)
    subrx_if = get_param("IF", rx, subrx)
    print(subrx_if)
    curr_freq = rx_dds + subrx_if
    if val == MIDI.ENCDOWN:
        idx = bisect_left(BANDS.POINTS, curr_freq) - 1
    elif val == MIDI.ENCUP:
        idx = bisect_right(BANDS.POINTS, curr_freq)
    else:
        return []

    if idx >= len(BANDS.POINTS):
        idx = 0
    rx_dds = BANDS.POINTS[idx]
    print(idx,rx_dds)
    subrx_if = 0

    return [ tci.COMMANDS["DDS"].prepare_string(TciCommandSendAction.WRITE, rx=rx, params=[int(rx_dds)]),
             tci.COMMANDS["IF"].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[int(subrx_if)]) ]

def do_freq_scroll(incr, val, rx, subrx):
    rx_dds = get_param("DDS", rx, subrx)
    subrx_if = get_param("IF", rx, subrx)
    subrx0_if = get_param("IF", rx, 0)
    if_lims = get_param("IF_LIMITS")

    # print(f"rx_dds is {rx_dds}, subrx_if is {subrx_if}, su")

    if val == MIDI.CLICK:
        if subrx == 0:
            rx_dds = rx_dds + subrx_if
            subrx_if = 0
        else:
            subrx_if = subrx0_if
    elif val == MIDI.ENCDOWN:
        subrx_if -= incr
    elif val == MIDI.ENCUP:
        subrx_if += incr
    else:
        return []

    if subrx_if < if_lims[0]:
        subrx_if = if_lims[0]
    if subrx_if > if_lims[1]:
        subrx_if = if_lims[1]

    return [ tci.COMMANDS["DDS"].prepare_string(TciCommandSendAction.WRITE, rx=rx, params=[int(rx_dds)]),
             tci.COMMANDS["IF"].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[int(subrx_if)]) ]

def do_filter_scroll(side, val, rx, subrx):
    flt = get_param("RX_FILTER_BAND", rx, subrx)
    mod = get_param("MODULATION", rx, subrx)

    if val == MIDI.CLICK:
        if side == FILTERSIDE.LEFT or side == FILTERSIDE.MAIN:
            flt[0] = MODS.DEFAULT_LEFT[mod]
        if side == FILTERSIDE.RIGHT or side == FILTERSIDE.MAIN:
            flt[1] = MODS.DEFAULT_RIGHT[mod]
    elif val == MIDI.ENCDOWN:
        if side == FILTERSIDE.LEFT:
            flt[0] -= 25
        if side == FILTERSIDE.MAIN:
            flt[0] -= MODS.WHEEL_LEFT[mod]
            flt[1] -= MODS.WHEEL_RIGHT[mod]
        if side == FILTERSIDE.RIGHT:
            flt[1] -= 25
    elif val == MIDI.ENCUP:
        if side == FILTERSIDE.LEFT:
            flt[0] += 25
        if side == FILTERSIDE.MAIN:
            flt[0] += MODS.WHEEL_LEFT[mod]
            flt[1] += MODS.WHEEL_RIGHT[mod]
        if side == FILTERSIDE.RIGHT:
            flt[1] += 25
    else:
        return []

    return [ tci.COMMANDS["RX_FILTER_BAND"].prepare_string(TciCommandSendAction.WRITE, rx=rx, params=flt) ]

def do_mod_scroll(val, rx, subrx):
    mod_list = get_param("MODULATIONS_LIST")
    # There are many modulations exposed in this list that aren't in the interface
    # The list included in the MODS constant matches the EESDR v3 beta interface for obvious scroll order
    mod = get_param("MODULATION", rx, subrx)
    midx = MODS.UI_LIST.index(mod)

    if val == MIDI.ENCDOWN:
        midx -= 1
        if midx < 0:
            midx = MODS.UI_LIST_MAX
    elif val == MIDI.ENCUP:
        midx += 1
        if midx > MODS.UI_LIST_MAX:
            midx = 0
    else:
        return []

    return [ tci.COMMANDS["MODULATION"].prepare_string(TciCommandSendAction.WRITE, rx=rx, params=[MODS.UI_LIST[midx]]) ]
                    
def do_enable_toggle(val, rx, subrx):
    if val == MIDI.CLICK:
        if rx > 0 and subrx == 0:
            return do_toggle("RX_ENABLE", MIDI.KEYDOWN, rx, subrx)
        elif subrx > 0:
            return do_toggle("RX_CHANNEL_ENABLE", MIDI.KEYDOWN, rx, subrx)
        else:
            return [ tci.COMMANDS["IF"].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[0]) ]
    else:
        return []

def do_toggle(name, val, rx, subrx):
    if val == MIDI.KEYDOWN or val == MIDI.CLICK:
        cv = not get_param(name, rx, subrx)
        # print(f"cv in do_toggle is {cv}")
        return [ tci.COMMANDS[name].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[cv]) ]
    else:
        return []

def do_momentary(name, val, rx, subrx):
    cv = (val == MIDI.KEYDOWN)
    # print(f"cv in do_momentary is {cv}")
    return [ tci.COMMANDS[name].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[cv]) ]

def do_generic_scroll(name, incr, val, rx, subrx):
    cv = get_param(name, rx, subrx)
    # print(f"cv in do_generic_scroll is {cv}")

    if val == MIDI.ENCDOWN:
        cv -= incr
    elif val == MIDI.ENCUP:
        cv += incr
    else:
        return []

    return [ tci.COMMANDS[name].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[cv]) ]

def do_generic_set(name, sp, val, rx, subrx):
    if val == MIDI.KEYDOWN or val == MIDI.CLICK:
        return [ tci.COMMANDS[name].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[sp]) ]
    else:
        return []

def do_volume_reset(val, rx, subrx):
    if val == MIDI.KEYDOWN or val == MIDI.CLICK:
        return [ tci.COMMANDS["RX_BALANCE"].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[0]),
                 tci.COMMANDS["RX_VOLUME"].prepare_string(TciCommandSendAction.WRITE, rx=rx, sub_rx=subrx, params=[0]) ]
    else:
        return []

async def run_cmds(tci_listener, cmds):
    for c in cmds:
        await tci_listener.send(c)

def midi_stream():
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()
    def callback(msg):
        loop.call_soon_threadsafe(queue.put_nowait, msg)
    async def stream():
        while True:
            yield await queue.get()
    return callback, stream()

async def midi_rx(tci_listener, midi_port):
    global params_dict, trx_cmd
    lower_filter = 200
    higher_filter = 200
    curr_subx = 0
    curr_rx = 0
    knob_plane = 0

    cb, stream = midi_stream()
    mido.open_input(midi_port, virtual = False, callback=cb)
    # print(f"cb is {cb} and stream is {stream}", )
    mod = get_param("MODULATION", curr_rx, curr_subx)
    print(f"mod is {mod}")
    if mod == "CW":
        vfo_step = 25
    else:
        vfo_step = 100
    print(f"vfo_step is {vfo_step}")
    async for msg in stream:
        print(f"MIDI is {msg}")
        rit_step = 10
        trx_cmd = ""
        strmsg = str(msg)
        isButton = strmsg[0:7]
        # print(isButton)    
        if midi_port == "DJControl Compact 0":
            cc = DJ
            if isButton == "control": # A JOG or a potentiometer has been turned
                if msg.control == cc.CROSSFADER:         # Power 0 to 100%
                    val = (100 * msg.value) / 127
                    trx_cmd = f"DRIVE:{curr_rx},{val};"
                elif msg.control == cc.JOGA:             # Frequency Scroll
                    trx_cmd = do_freq_scroll(vfo_step, msg.value, curr_rx, curr_subx)
                elif msg.control == cc.JOGB:             # Frequency Scroll
                    trx_cmd = do_generic_scroll("RIT_OFFSET", rit_step, msg.value, curr_rx, curr_subx)
                elif msg.control == cc.POTVOLUMEA:       # Volume 0 to -60 dB 
                    val = (60 * msg.value) / 127
                    trx_cmd = f"VOLUME:{-val};"
                elif msg.control == cc.POTVOLUMEB:       # Monitor Volume 0 to -60 dB
                    val = (60 * msg.value) / 127
                    trx_cmd = f"MON_VOLUME:{-val};"
                elif msg.control == cc.POTBASSA:         # Value of the RX filter low
                    if higher_filter == None: higher_filter = 200
                    lower_filter = msg.value * 5
                    trx_cmd = f"RX_FILTER_BAND:{curr_rx},-{lower_filter},{higher_filter};"
                elif msg.control == cc.POTBASSB:         # Value of the RX filter hight
                    if lower_filter == None: lower_filter = 200
                    higher_filter = msg.value * 5
                    trx_cmd = f"RX_FILTER_BAND:{curr_rx},-{lower_filter},{higher_filter};"
                # await tci_listener.send(trx_cmd)
            elif isButton == "note_on": # I press a button
                if msg.note == cc.BTN_PLAY_A and msg.velocity == MIDI.KEYDOWN:       # Listen with VFOB
                    curr_subx = 1
                    trx_cmd = do_toggle("RX_CHANNEL_ENABLE", MIDI.KEYDOWN, curr_rx, 1)
                elif msg.note == cc.BTN_CUE_A and msg.velocity == MIDI.KEYDOWN:     # Equalize VFOs
                    TXFreqVFOA = get_param("VFO", curr_rx, 0)
                    trx_cmd = f"VFO:{curr_rx},1,{TXFreqVFOA};"      # VFO A --> B
                elif msg.note == cc.BTN_SYNC_A and msg.velocity == MIDI.KEYDOWN:     # Select RX
                    curr_subx = 0
                elif msg.note == cc.BTN_PLAY_B and msg.velocity == MIDI.KEYDOWN:     # Toggle RIT on RX2
                    curr_rx = 1
                    trx_cmd = do_toggle("RIT_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.note == cc.BTN_SYNC_B and msg.velocity == MIDI.KEYDOWN:     # Toggle RIT on RX1
                    curr_rx = 0
                    trx_cmd = do_toggle("RIT_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.note == cc.BTN_CUE_B and msg.velocity == MIDI.KEYDOWN:      # Clear RIT
                    trx_cmd = f"RIT_OFFSET:{curr_rx},0;"
                elif msg.note == cc.BTN_AUTOMIX and msg.velocity == MIDI.KEYDOWN:    # Toggle Monitor On/Off 
                    trx_cmd = do_toggle("MON_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.note == cc.BTN_REC and msg.velocity == MIDI.KEYDOWN:        # Toggle Mute On/Off
                    trx_cmd = do_toggle("MUTE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.note == cc.BTN_MODE and msg.velocity == MIDI.KEYDOWN:       # Change Mode Up 
                    trx_cmd = do_mod_scroll(MIDI.ENCDOWN, curr_rx, curr_subx)
                elif msg.note == cc.BTN_SHIFT and msg.velocity == MIDI.KEYDOWN:      # Change Mode Down
                    trx_cmd = do_mod_scroll(MIDI.ENCUP, curr_rx, curr_subx)
                elif msg.note == cc.BTN_1A and msg.velocity == MIDI.KEYDOWN:         # SWAP VFOs
                    TXFreqVFOA = get_param("VFO", curr_rx, 0)
                    TXFreqVFOB = get_param("VFO", curr_rx, 1)
                    trx_cmd = f"VFO:{curr_rx},1,{TXFreqVFOA};"      # VFO A = B
                    await tci_listener.send(trx_cmd)
                    trx_cmd = f"VFO:{curr_rx},0,{TXFreqVFOB};"      # Now Swap VFO
                    print(f"TXFreq is {TXFreqVFOA} and {TXFreqVFOB}")
                elif msg.note == cc.BTN_2A and msg.velocity == MIDI.KEYDOWN:     # Toggle RX focus
                    if vfo_step == 200:
                        vfo_step = 25
                    else: vfo_step *= 2
                    print(f"vfo_step is {vfo_step}")
                elif msg.note == cc.BTN_3A and msg.velocity == MIDI.KEYDOWN:    # TX on when button down, RX is back when button up
                    trx_cmd = f"TRX:{curr_rx},true;"
                elif msg.note == cc.BTN_3A and msg.velocity == MIDI.KEYUP:   # TX on when button down, RX is back when button up
                    trx_cmd = f"TRX:{curr_rx},false;"
                elif msg.note == cc.BTN_4A and msg.velocity == MIDI.KEYDOWN:
                    mod = get_param("MODULATION", curr_rx, curr_subx)
                    print(f"mod is {mod}")
                    if mod == "CW":
                        trx_cmd = "RX_FILTER_BAND:0,-100,100;"                      # User filter is now 200 Hz Wide
                    elif mod == "LSB":
                        trx_cmd = "RX_FILTER_BAND:0,-2400,10;"                    # User filter is now 2400 Hz Wide
                    elif mod == "USB":
                        trx_cmd = "RX_FILTER_BAND:0,10,2400;"                       # User filter is now 2400 Hz Wide
                        
                elif msg.note == cc.BTN_1B and msg.velocity == MIDI.KEYDOWN:       # Listen with VFOB
                    curr_subx = 1
                    trx_cmd = do_toggle("SPLIT_ENABLE", MIDI.KEYDOWN, curr_rx, 1)
                elif msg.note == cc.BTN_2B and msg.velocity == MIDI.KEYDOWN: # Toggle RX2 On/Off
                    trx_cmd = do_toggle("RX_ENABLE", MIDI.KEYDOWN, 1, None)
                    print(f"trx_cmd is {trx_cmd}")
                elif msg.note == cc.BTN_3B and msg.velocity == MIDI.KEYDOWN: # Toggle Mute RX1 On/Off
                    trx_cmd = do_toggle("RX_MUTE", MIDI.KEYDOWN, 0, None)
                    print(f"trx_cmd is {trx_cmd}")
                elif msg.note == cc.BTN_4B and msg.velocity == MIDI.KEYDOWN: # Toggle Mute RX2 On/Off
                    trx_cmd = do_toggle("RX_MUTE", MIDI.KEYDOWN, 1, None)
                    print(f"trx_cmd is {trx_cmd}")
                # await tci_listener.send(trx_cmd)
                # print(f"message complet is {msg}")
        elif midi_port == "DJControl Starlight 0": 
            cc = DJS # It is the starlight (No other device is supported)
            # print(isButton)
            if isButton == "control":
                if msg.channel == 0:
                    if msg.control == cc.CROSSFADER:         # Power 0 to 100%
                        val = (100 * msg.value) / 127
                        trx_cmd = f"DRIVE:{curr_rx},{val};"
                    elif msg.control == cc.POTVOLUME1:       # Volume 0 to -60 dB 
                        val = (60 * msg.value) / 127
                        trx_cmd = f"VOLUME:{-val};"
                    elif msg.control == cc.POTVOLUME2:       # Monitor Volume 0 to -60 dB
                        val = (60 * msg.value) / 127
                        trx_cmd = f"MON_VOLUME:{-val};"
                elif msg.channel == 1:     # Left side of the DJControl Starlight
                    if msg.control == cc.JOG:             # Frequency Scroll
                        trx_cmd = do_freq_scroll(vfo_step, msg.value, curr_rx, curr_subx)
                    elif msg.control == cc.POTBASS:           # Filter Scroll
                        trx_cmd = do_filter_scroll(FILTERSIDE.LEFT, msg.value * 10, curr_rx, curr_subx)
                elif msg.channel == 2:     # Right side of the DJControl Starlight
                    if msg.control == cc.JOG:             # Frequency Scroll
                        trx_cmd = do_generic_scroll("RIT_OFFSET", rit_step, msg.value, curr_rx, curr_subx)
                    elif msg.control == cc.POTBASS:           # Filter Scroll
                        trx_cmd = do_filter_scroll(FILTERSIDE.RIGHT, msg.value * 10, curr_rx, curr_subx)
            elif isButton == "note_on": # Starlight buttons
                if msg.channel == 0:
                    if msg.note == cc.BTN_SHIFT and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_mod_scroll(MIDI.ENCDOWN, curr_rx, curr_subx)
                elif msg.channel == 1:
                    if msg.note == cc.BTN_SHIFT and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_mod_scroll(MIDI.ENCUP, curr_rx, curr_subx)
                    elif msg.note == cc.BTN_PLAY and msg.velocity == MIDI.KEYDOWN:
                        curr_subx = 1
                        trx_cmd = do_toggle("RX_CHANNEL_ENABLE", MIDI.KEYDOWN, curr_rx, 1)
                    elif msg.note == cc.BTN_CUE and msg.velocity == MIDI.KEYDOWN:
                        TXFreqVFOA = get_param("VFO", curr_rx, 0)
                        trx_cmd = f"VFO:{curr_rx},1,{TXFreqVFOA};"      # VFO A --> B
                    elif msg.note == cc.BTN_SYNC and msg.velocity == MIDI.KEYDOWN:
                        curr_subx = 0
                    elif msg.note == cc.BTN_HELMET and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_toggle("MUTE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.channel == 2:
                    if msg.note == cc.BTN_PLAY and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_toggle("RIT_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                    elif msg.note == cc.BTN_CUE and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = f"RIT_OFFSET:{curr_rx},0;"
                    elif msg.note == cc.BTN_HOT and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_toggle("MON_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                    elif msg.note == cc.BTN_LOOP and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_toggle("MON_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                    elif msg.note == cc.BTN_HELMET and msg.velocity == MIDI.KEYDOWN:
                        trx_cmd = do_toggle("MON_ENABLE", MIDI.KEYDOWN, curr_rx, curr_subx)
                elif msg.channel == 6:
                    if msg.note == cc.BTN_1 and msg.velocity == MIDI.KEYDOWN: # SWAP VFOs
                        TXFreqVFOA = get_param("VFO", curr_rx, 0)
                        TXFreqVFOB = get_param("VFO", curr_rx, 1)
                        trx_cmd = f"VFO:{curr_rx},1,{TXFreqVFOA};"      # VFO A = B
                        await tci_listener.send(trx_cmd)
                        trx_cmd = f"VFO:{curr_rx},0,{TXFreqVFOB};"      # Now Swap VFO
                        print(f"TXFreq is {TXFreqVFOA} and {TXFreqVFOB}")
                    elif msg.note == cc.BTN_2 and msg.velocity == MIDI.KEYDOWN: # change vfo_step
                        if vfo_step == 200:
                            vfo_step = 25
                        else: vfo_step *= 2
                        print(f"vfo_step is {vfo_step}")
                    elif msg.note == cc.BTN_3 and msg.velocity == MIDI.KEYDOWN: # TX on when button down, RX is back when button up
                        trx_cmd = f"TRX:{curr_rx},true;"
                    elif msg.note == cc.BTN_3 and msg.velocity == MIDI.KEYUP:   # TX on when button down, RX is back when button up
                        trx_cmd = f"TRX:{curr_rx},false;"
                    elif msg.note == cc.BTN_4 and msg.velocity == MIDI.KEYDOWN: # Change filter
                        mod = get_param("MODULATION", curr_rx, curr_subx)
                        print(f"mod is {mod}")
                        if mod == "CW":
                            trx_cmd = "RX_FILTER_BAND:0,-100,100;"
                            print("CW Filter is 200 Hz")
                        elif mod == "LSB":
                            trx_cmd = "RX_FILTER_BAND:0,-2400,10;"
                            print("LSB Filter is 2400 Hz")
                        elif mod == "USB":
                            trx_cmd = "RX_FILTER_BAND:0,10,2400;"
                            print("USB Filter is 2400 Hz")
                    elif msg.note == cc.BTN_4L and msg.velocity == MIDI.KEYDOWN: # Change filter
                        mod = get_param("MODULATION", curr_rx, curr_subx)
                        print(f"mod is {mod}")
                        if mod == "CW":
                            trx_cmd = "RX_FILTER_BAND:0,-250,250;"
                            print("CW Filter is 500 Hz")
                        elif mod == "LSB":
                            trx_cmd = "RX_FILTER_BAND:0,-3000,10;"
                            print("LSB Filter is 3 kHz")
                        elif mod == "USB":
                            trx_cmd = "RX_FILTER_BAND:0,10,3000;"
                            print("USB Filter is 3 kHz")
                # print("It is the starlight and except")
        await tci_listener.send(trx_cmd)
async def main(uri, midi_port):
    tci_listener = Listener(uri)
    tci_listener.add_param_listener("*", update_params)
    await tci_listener.start()
    await tci_listener.ready()
    asyncio.create_task(midi_rx(tci_listener, midi_port))
    await tci_listener.wait()
# cfg = Config("config.json")
# uri = cfg.get("uri", required=True)
# midi_port = cfg.get("midi_port", required=True)
uri = "ws://localhost:50001"
# midi_port = "DJControl Compact 0"
print(f"midi_port is {midi_port} and uri is {uri}")

asyncio.run(main(uri, midi_port))
