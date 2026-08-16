# How Rev A USB serial LCDs send pixels (research notes)
#
# Sources (open-source / reverse notes; device id USB35INCHIPSV2):
# - vendor tree: library/lcd/lcd_comm_rev_a.py
# - viktorkav/usb-lcd-dashboard shared.py
# - common host utilities: SerialPort, DTR/RTS, baud, Flush
#
# Serial open:
#   baud = 115200
#   rtscts = True          # REQUIRED for bulk bitmap transfer
#   dtr = True, rts = True # host typically asserts these
#   no write_timeout       # let RTS/CTS pace the host
#
# Frame protocol:
#   1) HELLO: 0x45 x6, read 6 bytes (01x6 = common 3.5" panel reply)
#   2) optional SCREEN_ON / SET_BRIGHTNESS (6-byte cmd)
#   3) DISPLAY_BITMAP (cmd 197) with x,y,ex,ey in packed 6-byte header
#   4) raw RGB565 little-endian pixels, chunk size = width * 8 (= 2560 for 320px)
#   5) flush() after EVERY chunk  <-- missing this caused our Windows hangs
#
# What we did wrong earlier:
#   - rtscts=False for bulk writes
#   - write_timeout retries fighting flow control
#   - no per-chunk flush
