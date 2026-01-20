-- mGBA Lua: stream Pokemon Emerald party + "state flags" bundle to Python (NDJSON),
-- AND accept control commands from Python to inject inputs (A/B/START/DPAD/etc).
--
-- Telemetry:  Lua -> Python  (HOST:PORT)      e.g. 127.0.0.1:7777
-- Control:    Python -> Lua  (HOST:PORT+1)    e.g. 127.0.0.1:7778
--
-- Control protocol (newline-delimited):
--   "A 2"            -> press A for 2 frames
--   "UP+LEFT 6"      -> hold UP+LEFT for 6 frames
--   "NONE 0"         -> release
--
-- Notes:
-- - Uses send_all() to prevent truncated JSON.
-- - Proper JSON null handling for unknown addresses.
-- - Auto-finds gMain in IWRAM to read callback1/callback2.
-- - Derives robust flags (battle/menu/overworld/dialog/cutscene/transition/control).
-- - Injects keys on the "keysRead" callback (best timing).
--
-- ROM: Pokemon - Emerald Version (USA, Europe)

local HOST = "127.0.0.1"
local PORT = 7777
local CONTROL_PORT = PORT + 1

-- =========================
-- Party block
-- =========================
local PARTY_BASE_PRIMARY = 0x020244EC
local PARTY_LEN = 600 -- 6 mons * 100 bytes

-- =========================
-- Opponent party block
-- =========================
local OPPONENT_PARTY_BASE_PRIMARY = 0x02024744

-- Stream rate: every N frames (GBA ~60fps; 6 => ~10Hz; 600 => ~0.1Hz)
local SEND_EVERY_N_FRAMES = 600 -- every 30 seconds

-- =========================
-- Addresses (optional)
-- Leave as 0 to emit null in JSON (valid)
-- =========================
local ADDR = {
  -- Core "what mode am I in?"
  gBattleTypeFlags         = 0x00000000, -- u32 (0 when not in battle)

  -- gMain auto-find (if you know it, set these; otherwise auto-find)
  gMain_base               = 0x00000000, -- base of gMain struct (optional)
  gMain_callback1_offset   = 0x00000000, -- usually 0x0
  gMain_callback2_offset   = 0x00000004, -- usually 0x4

  -- Script contexts (dialog/cutscene/event running)
  gScriptContext1_isActive = 0x00000000, -- u8/bool
  gScriptContext2_isActive = 0x00000000, -- u8/bool

  -- Fade / transition
  gPaletteFade_active      = 0x00000000, -- u8/bool-ish

  -- Optional / later:
  gPlayerAvatar_flags      = 0x00000000, -- u16 (if you wire it)

  gObjectEvents = 0x02037590,
  gPlayerAvatar = 0x020375B4

}

-- =========================
-- Helpers: socket send (prevents truncated JSON)
-- =========================
local function send_all(sock, data)
  local total = #data
  local sent = 0
  while sent < total do
    local chunk = data:sub(sent + 1)
    local n, err = sock:send(chunk)

    if n == nil then
      return nil, err
    end

    if type(n) == "number" then
      if n <= 0 then
        return nil, "send returned " .. tostring(n)
      end
      sent = sent + n

    elseif type(n) == "boolean" then
      -- Some mGBA builds return true/false instead of byte count.
      if n == true then
        sent = total
      else
        return nil, "send returned false"
      end

    else
      return nil, "send returned unexpected type: " .. type(n)
    end
  end
  return true
end

-- =========================
-- Helpers: encoding + reads
-- =========================
local function to_hex(bytestr)
  return (bytestr:gsub(".", function(c)
    return string.format("%02x", string.byte(c))
  end))
end

local function read_u8(addr)
  if addr == 0 or addr == nil then return nil end
  return emu:read8(addr)
end

local function read_u16_le(addr)
  if addr == 0 or addr == nil then return nil end
  local lo = emu:read8(addr)
  local hi = emu:read8(addr + 1)
  return lo + hi * 256
end

local function read_u32_le(addr)
  if addr == 0 or addr == nil then return nil end
  local b0 = emu:read8(addr)
  local b1 = emu:read8(addr + 1)
  local b2 = emu:read8(addr + 2)
  local b3 = emu:read8(addr + 3)
  return b0 + b1 * 256 + b2 * 65536 + b3 * 16777216
end

local function read_s16_le(addr)
  if addr == 0 or addr == nil then return nil end
  local v = read_u16_le(addr)
  if v == nil then return nil end
  if v >= 0x8000 then v = v - 0x10000 end
  return v
end

-- Emerald (symbols branch): gSaveBlock1Ptr is stored in IWRAM here
local G_SAVE_BLOCK1_PTR = 0x03005D8C

local function read_u32_le(addr)
  local b0 = emu:read8(addr)
  local b1 = emu:read8(addr + 1)
  local b2 = emu:read8(addr + 2)
  local b3 = emu:read8(addr + 3)
  return b0 + b1 * 256 + b2 * 65536 + b3 * 16777216
end

local function read_u16_le(addr)
  local lo = emu:read8(addr)
  local hi = emu:read8(addr + 1)
  return lo + hi * 256
end

-- Player location in SaveBlock1 (tile coords):
-- x: u16 @ +0x00
-- y: u16 @ +0x02
-- mapGroup: u8 @ +0x04
-- mapNum: u8 @ +0x05
local function read_player_pos_from_saveblock1()
  local sb1 = read_u32_le(G_SAVE_BLOCK1_PTR)
  if sb1 == nil or sb1 == 0 then return nil end

  local x = read_u16_le(sb1 + 0x00)
  local y = read_u16_le(sb1 + 0x02)
  local mapGroup = emu:read8(sb1 + 0x04)
  local mapNum   = emu:read8(sb1 + 0x05)

  return {
    x = x,
    y = y,
    mapGroup = mapGroup,
    mapNum = mapNum,
    saveBlock1 = sb1,
  }
end

-- Reads player overworld position from ObjectEvent
local function read_player_overworld_pos()
  if ADDR.gPlayerAvatar == 0 or ADDR.gObjectEvents == 0 then
    return nil
  end

  local objectEventId = read_u8(ADDR.gPlayerAvatar + 0x05) -- PlayerAvatar.objectEventId
  if objectEventId == nil then
    return nil
  end

  local oe_base = ADDR.gObjectEvents + objectEventId * 0x24 -- sizeof(ObjectEvent)=0x24

  local x = read_s16_le(oe_base + 0x10) -- currentCoords.x
  local y = read_s16_le(oe_base + 0x12) -- currentCoords.y
  local mapNum = read_u8(oe_base + 0x09)
  local mapGroup = read_u8(oe_base + 0x0A)

  return {
    objectEventId = objectEventId,
    x = x,
    y = y,
    mapNum = mapNum,
    mapGroup = mapGroup,
  }
end

-- JSON-safe rendering: nil -> null
local function json_num(v)
  if v == nil then return "null" end
  return tostring(v)
end

local function json_str(s)
  if s == nil then return "null" end
  s = tostring(s)
  s = s:gsub("\\", "\\\\")
  s = s:gsub("\"", "\\\"")
  return "\"" .. s .. "\""
end

-- =========================
-- Auto-find gMain (optional, but very helpful)
-- Identify gMain by matching heldKeysRaw against KEYINPUT.
-- Layout used (Emerald):
--   +0x00 callback1 (u32 ptr)
--   +0x04 callback2 (u32 ptr)
--   +0x28 heldKeysRaw (u16)
-- =========================
local GMAIN_IWRAM_START = 0x03000000
local GMAIN_IWRAM_END   = 0x03008000
local gMain_addr = nil

local function read_keys_raw()
  local keyinput = emu:read16(0x04000130) -- 0=pressed, 1=released
  return (~keyinput) & 0x03FF             -- pressed bits
end

local function is_rom_ptr(x)
  return x ~= nil and x >= 0x08000000 and x < 0x0A000000
end


local function read_callbacks()
  local base = nil
  if ADDR.gMain_base ~= nil and ADDR.gMain_base ~= 0 then
    base = ADDR.gMain_base
  elseif gMain_addr ~= nil then
    base = gMain_addr
  end

  if base == nil then
    return nil, nil, nil
  end

  local off1 = ADDR.gMain_callback1_offset or 0x00
  local off2 = ADDR.gMain_callback2_offset or 0x04
  local cb1 = read_u32_le(base + off1)
  local cb2 = read_u32_le(base + off2)
  return base, cb1, cb2
end

-- =========================
-- callback2 self-learning to distinguish overworld vs menu-ish
-- =========================
local cb2_hist = {}
local overworld_cb2 = nil

local function bump_cb2(cb2)
  if cb2 == nil or cb2 == 0 then return end
  cb2_hist[cb2] = (cb2_hist[cb2] or 0) + 1

  local best_cb2, best_n = overworld_cb2, -1
  for k, v in pairs(cb2_hist) do
    if v > best_n then
      best_n = v
      best_cb2 = k
    end
  end
  overworld_cb2 = best_cb2
end

-- =========================
-- "Max flags" derivation
-- Works even when some raw values are nil.
-- =========================
local function derive_flags(sig)
  local battle = (sig.battleTypeFlags ~= nil and sig.battleTypeFlags ~= 0) and 1 or 0

  local script1 = (sig.script1Active ~= nil and sig.script1Active ~= 0) and 1 or 0
  local script2 = (sig.script2Active ~= nil and sig.script2Active ~= 0) and 1 or 0
  local scripted = (script1 == 1 or script2 == 1) and 1 or 0

  local fading = (sig.paletteFadeActive ~= nil and sig.paletteFadeActive ~= 0) and 1 or 0

  -- Learn overworld cb2 only when NOT in battle
  if battle == 0 then
    bump_cb2(sig.cb2)
  end

  local cb2_known = (sig.cb2 ~= nil and sig.cb2 ~= 0 and overworld_cb2 ~= nil)
  local cb2_is_overworld = (cb2_known and sig.cb2 == overworld_cb2) and 1 or 0
  local cb2_is_non_overworld = (cb2_known and sig.cb2 ~= overworld_cb2) and 1 or 0

  local overworld = 0
  if battle == 0 then
    if cb2_known then
      overworld = cb2_is_overworld
    else
      overworld = (scripted == 0 and fading == 0) and 1 or 0
    end
  end

  local menu = 0
  if battle == 0 then
    if cb2_known and cb2_is_non_overworld == 1 then
      menu = 1
    elseif scripted == 0 and fading == 1 then
      menu = 1
    end
  end

  local dialog = scripted
  local cutscene = (script2 == 1) and 1 or 0
  if cutscene == 0 and scripted == 1 and cb2_known and cb2_is_non_overworld == 1 then
    cutscene = 1
  end

  local locked = (script2 == 1) and 1 or 0
  if locked == 0 and fading == 1 then
    locked = 1
  end
  local has_control = (locked == 0 and battle == 0 and fading == 0) and 1 or 0

  local mode = "UNKNOWN"
  if battle == 1 then
    mode = "BATTLE"
  elseif fading == 1 then
    mode = "TRANSITION"
  elseif menu == 1 then
    mode = "MENU"
  elseif cutscene == 1 then
    mode = "CUTSCENE"
  elseif dialog == 1 then
    mode = "DIALOG"
  elseif overworld == 1 then
    mode = "OVERWORLD"
  end

  return {
    in_battle = battle,
    in_overworld = overworld,
    in_menu = menu,

    in_script = scripted,
    in_dialog = dialog,
    in_cutscene = cutscene,

    in_transition = fading,
    player_locked = locked,
    has_player_control = has_control,

    overworld_cb2 = overworld_cb2,
    cb2_is_overworld = cb2_is_overworld,
  }, mode
end

-- =========================
-- Control socket (Lua -> Python connect) + key injection (non-blocking)
-- =========================
local ctrl = nil
local ctrl_buf = ""

local hold_mask = 0
local hold_frames_left = 0

local KEYMAP = {
  A="A", B="B", START="START", SELECT="SELECT",
  UP="UP", DOWN="DOWN", LEFT="LEFT", RIGHT="RIGHT",
  L="L", R="R",
}

local ALIASES = {
  U="UP", D="DOWN", LFT="LEFT", RGT="RIGHT",
  LEFT_ARROW="LEFT", RIGHT_ARROW="RIGHT",
}

local function token_to_bit(token)
  local t = ALIASES[token] or token
  local name = KEYMAP[t]
  if not name then return nil end
  return C.GBA_KEY[name]
end

local function parse_control_line(line)
  line = line:gsub("\r", "")
  if line == "" then return end

  local keys_part, frames_part = line:match("^([^ ]+)%s*(%d*)$")
  local frames = tonumber(frames_part) or 2

  if not keys_part or keys_part == "NONE" or keys_part == "0" then
    hold_mask = 0
    hold_frames_left = 0
    return
  end

  local bits = {}
  for tok in keys_part:gmatch("[^%+]+") do
    local bit = token_to_bit(tok)
    if bit ~= nil then table.insert(bits, bit) end
  end

  hold_mask = util.makeBitmask(bits)
  hold_frames_left = frames
end

local function ensure_ctrl_connected()
  if ctrl ~= nil then return true end
  local s, err = socket.connect(HOST, CONTROL_PORT)
  if s then
    ctrl = s
    ctrl_buf = ""
    console:log(string.format("Connected to control server %s:%d", HOST, CONTROL_PORT))
    return true
  end
  -- Don’t spam logs every frame
  return false
end

local function pump_ctrl()
  if not ensure_ctrl_connected() then return end
  if not ctrl:hasdata() then return end

  local chunk, err = ctrl:receive(4096)
  if not chunk then
    console:warn("Control recv failed: " .. tostring(err))
    ctrl = nil
    ctrl_buf = ""
    hold_mask = 0
    hold_frames_left = 0
    return
  end

  ctrl_buf = ctrl_buf .. chunk
  while true do
    local nl = ctrl_buf:find("\n", 1, true)
    if not nl then break end
    local line = ctrl_buf:sub(1, nl - 1)
    ctrl_buf = ctrl_buf:sub(nl + 1)
    parse_control_line(line)
  end
end

callbacks:add("keysRead", function()
  pump_ctrl()
  if hold_frames_left > 0 then
    emu:setKeys(hold_mask)
    hold_frames_left = hold_frames_left - 1
  else
    emu:setKeys(0)
  end
end)
-- =========================
-- Telemetry socket connect (Lua -> Python)
-- =========================
console:log(string.format("Connecting telemetry to %s:%d ...", HOST, PORT))
local sock, err = socket.connect(HOST, PORT)
if not sock then
  console:error("Telemetry socket connect failed: " .. tostring(err))
  return
end
console:log("Connected! Streaming party + flags...")

local last_sent_frame = -999999

callbacks:add("shutdown", function()
  console:log("Shutting down script, closing sockets.")
  sock = nil
  control_client = nil
  control_server = nil
end)

-- =========================
-- Main loop (telemetry)
-- =========================
callbacks:add("frame", function()

  if sock == nil then return end

  local f = emu:currentFrame()
  if (f - last_sent_frame) < SEND_EVERY_N_FRAMES then
    return
  end
  last_sent_frame = f

  -- Party bytes
  local party_bytes = emu:readRange(PARTY_BASE_PRIMARY, PARTY_LEN)
  local party_hex = to_hex(party_bytes)

  local opponent_party_bytes = emu:readRange(OPPONENT_PARTY_BASE_PRIMARY, PARTY_LEN)
  local opponent_party_hex = to_hex(opponent_party_bytes)

  -- Callbacks (from gMain if possible)
  local gMainBase, cb1, cb2 = read_callbacks()

  -- Raw signals (nil if address unknown/0)
  local sig = {
    battleTypeFlags   = read_u32_le(ADDR.gBattleTypeFlags),
    cb1               = cb1,
    cb2               = cb2,
    script1Active     = read_u8(ADDR.gScriptContext1_isActive),
    script2Active     = read_u8(ADDR.gScriptContext2_isActive),
    paletteFadeActive = read_u8(ADDR.gPaletteFade_active),
    playerAvatarFlags = read_u16_le(ADDR.gPlayerAvatar_flags),
  }

  local ppos = read_player_pos_from_saveblock1()


  -- Derived flags + mode
  local flags, mode = derive_flags(sig)

  -- Screenshot
  emu:screenshot()


  -- NDJSON line
  local json_line = string.format(
    '{"frame":%d,' ..
      '"party_base":%d,"party_hex":"%s",' ..
      '"opponent_party_base":%d,"opponent_party_hex":"%s",' ..
      '"player":{' ..
          '"objectEventId":%s,' ..
          '"x":%s,' ..
          '"y":%s,' ..
          '"mapGroup":%s,' ..
          '"mapNum":%s' ..
        '},' ..
      '"sig":{' ..
        '"battleTypeFlags":%s,' ..
        '"gMainBase":%s,' ..
        '"cb1":%s,' ..
        '"cb2":%s,' ..
        '"script1Active":%s,' ..
        '"script2Active":%s,' ..
        '"paletteFadeActive":%s,' ..
        '"playerAvatarFlags":%s' ..
      '},' ..
      '"flags":{' ..
        '"mode":%s,' ..
        '"in_battle":%d,' ..
        '"in_overworld":%d,' ..
        '"in_menu":%d,' ..
        '"in_script":%d,' ..
        '"in_dialog":%d,' ..
        '"in_cutscene":%d,' ..
        '"in_transition":%d,' ..
        '"player_locked":%d,' ..
        '"has_player_control":%d,' ..
        '"cb2_is_overworld":%d,' ..
        '"overworld_cb2":%s' ..
      '}' ..
    '}\n',
    f,
    PARTY_BASE_PRIMARY, party_hex,
    OPPONENT_PARTY_BASE_PRIMARY, opponent_party_hex,
    json_num(ppos and ppos.objectEventId),
    json_num(ppos and ppos.x),
    json_num(ppos and ppos.y),
    json_num(ppos and ppos.mapGroup),
    json_num(ppos and ppos.mapNum),
    json_num(sig.battleTypeFlags),
    json_num(gMainBase),
    json_num(sig.cb1),
    json_num(sig.cb2),
    json_num(sig.script1Active),
    json_num(sig.script2Active),
    json_num(sig.paletteFadeActive),
    json_num(sig.playerAvatarFlags),

    json_str(mode),
    flags.in_battle,
    flags.in_overworld,
    flags.in_menu,
    flags.in_script,
    flags.in_dialog,
    flags.in_cutscene,
    flags.in_transition,
    flags.player_locked,
    flags.has_player_control,
    flags.cb2_is_overworld,
    json_num(flags.overworld_cb2)
  )

  local ok, send_err = send_all(sock, json_line)
  if not ok then
    console:warn("Telemetry send failed: " .. tostring(send_err))
  end
end)
