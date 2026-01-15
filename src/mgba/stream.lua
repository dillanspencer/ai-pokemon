-- mGBA Lua: stream Pokemon Emerald party + "state flags" bundle to a Python TCP server.
-- ROM: Pokemon - Emerald Version (USA, Europe)
--
-- NDJSON output: one JSON object per line (newline-delimited JSON).
--
-- Key upgrades in this rewrite:
-- 1) send_all() to prevent truncated JSON
-- 2) Proper JSON null handling for unknown addresses
-- 3) "Max flags" derived from:
--    - battleTypeFlags (battle)
--    - script contexts (dialog/cutscene)
--    - palette fade (transition)
--    - callback2 classification (overworld/menu) via self-learning histogram
-- 4) Adds extra useful derived flags:
--    - in_dialog (alias of in_script)
--    - in_cutscene (script2 OR scripted + not overworld)
--    - in_transition (palette fade)
--    - player_locked (script2 heuristic)
--    - has_player_control (inverse of player_locked + not in_transition)
--    - mode string (BATTLE/MENU/OVERWORLD/SCRIPT/TRANSITION/UNKNOWN)

local HOST = "127.0.0.1"
local PORT = 7777

-- =========================
-- Party block
-- =========================
local PARTY_BASE_PRIMARY = 0x020244EC
local PARTY_LEN = 600 -- 6 mons * 100 bytes

-- =========================
-- Opponent party block
-- =========================
local OPPONENT_PARTY_BASE_PRIMARY = 0x02024744

-- Stream rate: every N frames (GBA ~60fps, so 6 => ~10Hz)
local SEND_EVERY_N_FRAMES = 600

-- =========================
-- Addresses (optional)
-- Leave as 0 to emit null in JSON (valid)
--
-- NOTE: callback1/callback2 can be auto-found via gMain scanning,
-- but if you already know these addresses, set them and it will use them.
-- =========================
local ADDR = {
  -- Core "what mode am I in?"
  gBattleTypeFlags         = 0x00000000, -- u32 (0 when not in battle)

  -- If you know gMain base or callback fields, you can set these:
  -- Otherwise the script will try to auto-find gMain and read callback1/callback2 from it.
  gMain_base               = 0x00000000, -- base of gMain struct (optional)
  gMain_callback1_offset   = 0x00000000, -- usually 0x0 (optional if base set)
  gMain_callback2_offset   = 0x00000004, -- usually 0x4 (optional if base set)

  -- Script contexts (dialog/cutscene/event running)
  gScriptContext1_isActive = 0x00000000, -- u8/bool
  gScriptContext2_isActive = 0x00000000, -- u8/bool

  -- Fade / transition
  gPaletteFade_active      = 0x00000000, -- u8/bool-ish

  -- Optional / later:
  gPlayerAvatar_flags      = 0x00000000, -- u8/u16 (depends on what you choose)
}

local SCREENSHOT_PATH = "mgba_latest.png"     -- relative = usually ROM folder / working dir
local SCREENSHOT_TMP  = "mgba_latest.tmp.png" -- temp file for atomic replace

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

-- JSON-safe rendering: nil -> null
local function json_num(v)
  if v == nil then return "null" end
  return tostring(v)
end

local function json_bool_from01(v01)
  if v01 == nil then return "null" end
  return (v01 ~= 0) and "true" or "false"
end

local function json_str(s)
  if s == nil then return "null" end
  -- Minimal escaping for our mode labels / safe strings
  s = tostring(s)
  s = s:gsub("\\", "\\\\")
  s = s:gsub("\"", "\\\"")
  return "\"" .. s .. "\""
end

-- =========================
-- Auto-find gMain (optional, but very helpful)
-- We identify gMain by matching heldKeysRaw against KEYINPUT.
-- Layout used (Emerald):
--   +0x00 callback1 (u32 ptr)
--   +0x04 callback2 (u32 ptr)
--   +0x28 heldKeysRaw (u16)
-- =========================
local GMAIN_IWRAM_START = 0x03000000
local GMAIN_IWRAM_END   = 0x03008000
local gMain_addr = nil

local function read_keys_raw()
  local keyinput = emu:read16(0x04000130)       -- 0=pressed, 1=released
  return (~keyinput) & 0x03FF                   -- pressed bits
end

local function is_rom_ptr(x)
  return x ~= nil and x >= 0x08000000 and x < 0x0A000000
end

local function try_find_gMain()
  local keys = read_keys_raw()
  for addr = GMAIN_IWRAM_START, (GMAIN_IWRAM_END - 0x50), 4 do
    local cb1 = read_u32_le(addr + 0x00)
    local cb2 = read_u32_le(addr + 0x04)

    if (cb1 == 0 or is_rom_ptr(cb1)) and (cb2 == 0 or is_rom_ptr(cb2)) then
      local held = read_u16_le(addr + 0x28)
      if held == keys then
        gMain_addr = addr
        console:log(string.format("Found gMain at 0x%08X", addr))
        return true
      end
    end
  end
  return false
end

local function read_callbacks()
  -- Priority:
  -- 1) If user provided gMain_base, use it
  -- 2) Else if we found gMain via scan, use it
  -- 3) Else nil
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

  -- Learn overworld cb2 only when NOT in battle (battle callback2 would dominate histogram otherwise)
  if battle == 0 then
    bump_cb2(sig.cb2)
  end

  -- cb2-based classification if we have it
  local cb2_known = (sig.cb2 ~= nil and sig.cb2 ~= 0 and overworld_cb2 ~= nil)
  local cb2_is_overworld = (cb2_known and sig.cb2 == overworld_cb2) and 1 or 0
  local cb2_is_non_overworld = (cb2_known and sig.cb2 ~= overworld_cb2) and 1 or 0

  -- Overworld:
  -- Prefer cb2 classification if available; else fallback heuristic.
  local overworld = 0
  if battle == 0 then
    if cb2_known then
      overworld = cb2_is_overworld
    else
      -- fallback: calm state (no fade, no scripts)
      overworld = (scripted == 0 and fading == 0) and 1 or 0
    end
  end

  -- Menu:
  -- If cb2 says "non-overworld" and you're not in battle, it's typically menu or other non-field handler.
  -- Also, if fading without scripts, it's frequently menu/transition UI.
  local menu = 0
  if battle == 0 then
    if cb2_known and cb2_is_non_overworld == 1 then
      menu = 1
    elseif scripted == 0 and fading == 1 then
      menu = 1
    end
  end

  -- Dialog / cutscene flags:
  local dialog = scripted
  local cutscene = (script2 == 1) and 1 or 0
  if cutscene == 0 and scripted == 1 and cb2_known and cb2_is_non_overworld == 1 then
    cutscene = 1
  end

  -- Player control:
  local locked = (script2 == 1) and 1 or 0
  if locked == 0 and fading == 1 then
    locked = 1
  end
  local has_control = (locked == 0 and battle == 0) and 1 or 0

  -- Mode label (single best label)
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
    -- primary
    in_battle = battle,
    in_overworld = overworld,
    in_menu = menu,

    -- scripts / text / events
    in_script = scripted,
    in_dialog = dialog,
    in_cutscene = cutscene,

    -- transitions / control
    in_transition = fading,
    player_locked = locked,
    has_player_control = has_control,

    -- cb2 classifier
    overworld_cb2 = overworld_cb2,
    cb2_is_overworld = cb2_is_overworld,
  }, mode
end

-- =========================
-- Socket connect
-- =========================
console:log(string.format("Connecting to %s:%d ...", HOST, PORT))
local sock, err = socket.connect(HOST, PORT)
if not sock then
  console:error("Socket connect failed: " .. tostring(err))
  return
end
console:log("Connected! Streaming party + flags...")

local last_sent_frame = -999999

callbacks:add("shutdown", function()
  console:log("Shutting down script, closing socket.")
  sock = nil
end)

-- =========================
-- Main loop
-- =========================
callbacks:add("frame", function()
  if sock == nil then return end

  local f = emu:currentFrame()
  if (f - last_sent_frame) < SEND_EVERY_N_FRAMES then
    return
  end
  last_sent_frame = f

  -- Ensure we have gMain (if user didn't provide it)
  if (ADDR.gMain_base == nil or ADDR.gMain_base == 0) and gMain_addr == nil then
    try_find_gMain()
  end

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

  -- Derived flags + mode
  local flags, mode = derive_flags(sig)

    -- Screenshot (fast + stable). Prefer screenshotToImage if available.
  local okShot = false
  emu:screenshot("test")
  okShot = true

  -- NDJSON line
  local json_line = string.format(
    '{"frame":%d,' ..
      '"party_base":%d,"party_hex":"%s",' ..
      '"opponent_party_base":%d,"opponent_party_hex":"%s",' ..
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
    console:warn("Send failed: " .. tostring(send_err))
  end
end)
