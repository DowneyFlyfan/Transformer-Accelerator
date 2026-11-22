package tri_oracle_wac_softmax_types;
    typedef struct packed {
        logic [4:0] owner;
        logic score_tile, score_core;
        logic cfg_valid;
        logic [10:0] cfg_length;
        logic in_valid;
        logic signed [15:0] score;
        logic [9:0] size;
        logic out_ready;
    } request_t;
    typedef struct packed {
        logic cfg_ready, cfg_error, in_ready, out_valid, out_last;
        logic [15:0] probability;
    } response_t;
    function automatic logic [4:0] core_owner(input logic [4:0] head);
        return head >= 5'd20 ? head - 5'd20 : head;
    endfunction
endpackage
