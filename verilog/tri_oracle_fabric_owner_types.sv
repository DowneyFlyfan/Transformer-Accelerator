`timescale 1ns/1ps
package tri_oracle_fabric_owner_types;
  typedef struct packed {
    logic rst_n;
    logic load_valid;
    logic [4:0] load_core;
    logic [1:0] load_kind;
    logic [9:0] load_addr;
    logic [2047:0] load_data;
    logic [31:0] load_rows;
    logic cmd_valid;
    logic [4:0] cmd_clusters,cmd_weight,cmd_mask;
    logic [9:0] cmd_activation;
    logic [3:0] cmd_output;
    logic cmd_accumulate;
    logic [1:0] cmd_reduce;
    logic [2:0] core_select;
    logic [4:0] activation_reloaded;
    logic [4:0] out_ready;
  } request_t;
  typedef struct packed {
    logic load_error,cmd_ready;
    logic [4:0] out_valid;
    logic [19:0] out_output;
    logic [5119:0] out_data;
  } response_t;
endpackage
