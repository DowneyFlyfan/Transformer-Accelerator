proc require {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error $message}
}
try {
    source syn/tri_oracle_signal_repair_targets.tcl
    set tran {# Net / InstPin MaxTranTime TranTime TranSlack CellPort Remark
core/bank_mask[194]
    core/read_mask_reg[194]/DA 0.377r/0.377f 0.333r/0.582f 0.045r/-0.205f DFMQD1BWP12T40P140/DA R
    core/auxiliary[3].masks/g6822/Z 0.301r/0.301f 0.240r/0.391f 0.061r/-0.090f OR4D0BWP12T40P140/Z R
core/bank_mask[142]
    core/read_mask_reg[142]/DA 0.377r/0.377f 0.336r/0.567f 0.041r/-0.190f DFMQD1BWP12T40P140/DA R
*info: there are 3 max_tran violations in the design.
*info: 3 violations are real (remark R).}
    require {[tri_oracle_route_slew_targets $tran] eq [list {core/bank_mask[142]} {core/bank_mask[194]}]} "Wrong slew targets"
    require {[llength [tri_oracle_route_slew_targets {*info: there are 0 max_tran violations in the design.}]] == 0} "Zero slew result rejected"
    foreach bad [list {} [string map {there\ are\ 3 there\ are\ 4} $tran] \
        [string map {*info:\ there\ are\ 3 {unrelated_net
*info: there are 3}} $tran] \
        {    pin/D 0.377r/0.377f 0.333r/0.582f 0.045r/-0.205f DFMQD1BWP12T40P140/DA R
*info: there are 1 max_tran violations in the design.}] {
        require {[catch {tri_oracle_route_slew_targets $bad}]} "Incomplete slew report admitted"
    }
    tri_oracle_route_require_data_net signal_net false false false
    foreach flags {{true false false} {false true false} {false false true}} {
        require {[catch {tri_oracle_route_require_data_net protected_net {*}$flags}]} \
            "Clock, power or ground net admitted to data-only repair"
    }
    set cap {# Net / InstPin MaxCap Cap CapSlack CellPort Remark
core/storage[18].inputs/FE_PHN349159_words_21_5
    core/storage[18].inputs/words_reg[21][5]/Q 0.051 0.052 -0.001 SDFQD0BWP12T40P140/Q R
*info: there is 1 max_cap violation in the design.
*info: 1 violation is real (remark R).}
    require {[tri_oracle_route_capacitance_targets $cap] eq [list {core/storage[18].inputs/FE_PHN349159_words_21_5}]} \
        "Capacitance violation omitted"
    set glitch {NetName vlPeak vlView vhPeak vhView
#
n_34956 -0.01 setup_typ -0.003 setup_typ
Total number of glitch violations: 1}
    require {[tri_oracle_route_glitch_targets $glitch] eq {n_34956}} "Wrong glitch targets"
    require {[llength [tri_oracle_route_glitch_targets {Total number of glitch violations: 0}]] == 0} "Zero glitch result rejected"
    require {[catch {tri_oracle_route_glitch_targets [string map {violations:\ 1 violations:\ 2} $glitch]}]} "Truncated glitch report admitted"
    set antenna {Net core/compute/n_691408
  VIO: PAR / Ratio (28.1739 / 20.0000)
  VIO: PAR / Ratio (28.1739 / 20.0000)
Total number of process antenna violations: 2 Viols Number of nets violated: 1.}
    require {[tri_oracle_route_antenna_targets $antenna] eq {core/compute/n_691408}} "Wrong antenna targets"
    require {[llength [tri_oracle_route_antenna_targets {No Ant violations were found}]] == 0} "Zero antenna result rejected"
    require {[catch {tri_oracle_route_antenna_targets [string map {violated:\ 1 violated:\ 2} $antenna]}]} "Truncated antenna report admitted"
    puts "PASS: native slew, glitch and antenna target formats; incomplete reports rejected"
} on error {message options} {
    puts stderr $message
    exit 1
}
