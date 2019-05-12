open_hw
connect_hw_server
open_hw_target
current_hw_device [get_hw_devices xc7z020_1]
readback_hw_device [current_hw_device] -bin_file [lindex $argv 0]
