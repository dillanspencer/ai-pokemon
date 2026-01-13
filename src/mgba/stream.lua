-- mGBA Lua: stream Pokemon Emerald party data to a Python TCP server.
-- Uses mGBA built-in socket + emu:readRange APIs. :contentReference[oaicite:3]{index=3}

local HOST = "127.0.0.1"
local PORT = 7777

-- ---------------------------------------------------------------------------
local PARTY_BASE_PRIMARY = 0x020244EC
local PARTY_LEN = 600 -- 6 mons * 100 bytes

-- Stream rate: every N frames (GBA is ~60 fps, so 6 => ~10Hz)
local SEND_EVERY_N_FRAMES = 6

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function to_hex(bytestr)
  -- bytestr is a Lua string of raw bytes (from readRange)
  return (bytestr:gsub(".", function(c)
    return string.format("%02x", string.byte(c))
  end))
end

local function read_u16_le(addr)
  local lo = emu:read8(addr)
  local hi = emu:read8(addr + 1)
  return lo + hi * 256
end


-- ---------------------------------------------------------------------------
-- Socket connect
-- ---------------------------------------------------------------------------

console:log(string.format("Connecting to %s:%d ...", HOST, PORT))
local sock, err = socket.connect(HOST, PORT)
if not sock then
  console:error("Socket connect failed: " .. tostring(err))
  return
end
console:log("Connected! Streaming party data...")

local last_sent_frame = -999999

callbacks:add("shutdown", function()
  console:log("Shutting down script, closing socket.")
  -- No explicit close method documented; just let it be GC'd.
  sock = nil
end)

-- ---------------------------------------------------------------------------
-- Main loop (frame callback)
-- ---------------------------------------------------------------------------

callbacks:add("frame", function()
  local f = emu:currentFrame()
  if (f - last_sent_frame) < SEND_EVERY_N_FRAMES then
    return
  end
  last_sent_frame = f

  local base = PARTY_BASE_PRIMARY

  local party_bytes = emu:readRange(base, PARTY_LEN)
  local payload = {
    frame = f,
    party_base = base,
    party_hex = to_hex(party_bytes),
  }

  -- Build JSON manually (simple + fast)
  local json_line = string.format(
    '{"frame":%d,"party_base":%d,"party_hex":"%s"}\n',
    payload.frame,
    payload.party_base,
    payload.party_hex
  )

  local ok, send_err = sock:send(json_line)
  if not ok then
    console:warn("Send failed: " .. tostring(send_err))
  end
end)
