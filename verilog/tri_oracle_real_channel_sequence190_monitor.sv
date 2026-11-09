`timescale 1ns/1ps
// Test-only observer: every accepted channel must appear once in order, even
// when its quantized activation contributes zero to the final output sums.
module tri_oracle_real_channel_sequence190_monitor (
    input logic clk,rst_n,packet_valid,packet_ready,packet_last,packet_error,packet_fallback,
    input logic [31:0] packet_tag,
    input logic [7:0] packet_count,
    input logic [2559:0] packet_channels,
    output int channels_seen=0,packets_seen=0,
    output bit done=0
);
  bit stalled=0;
  logic [2602:0] held_packet;
  always @(posedge clk) begin
    if(!rst_n) begin channels_seen=0;packets_seen=0;done=0;stalled=0;end
    else begin
      if($isunknown({packet_valid,packet_ready})) $fatal(1,"REAL_CHANNEL_SEQUENCE_UNKNOWN");
      if(stalled && (packet_valid!==1 ||
          {packet_tag,packet_last,packet_fallback,packet_error,packet_count,packet_channels}!==held_packet))
        $fatal(1,"REAL_CHANNEL_SEQUENCE_STALLED_PACKET_CHANGED");
      stalled=packet_valid && !packet_ready;
      if(stalled) held_packet={packet_tag,packet_last,packet_fallback,packet_error,packet_count,packet_channels};
      if(packet_valid && packet_ready) begin
        if(done) $fatal(1,"REAL_CHANNEL_SEQUENCE_EXTRA");
        if(packet_tag!==32'h19001234 || packet_error!==0 || packet_fallback!==0)
          $fatal(1,"REAL_CHANNEL_SEQUENCE_METADATA");
        if(packet_count!==8'(5632-channels_seen>160?160:5632-channels_seen))
          $fatal(1,"REAL_CHANNEL_SEQUENCE_COUNT");
        if(packet_last!==(channels_seen+int'(packet_count)==5632))
          $fatal(1,"REAL_CHANNEL_SEQUENCE_LAST");
        for(int row=0;row<int'(packet_count);row++)
          if(packet_channels[row*16+:16]!==16'(channels_seen+row))
            $fatal(1,"REAL_CHANNEL_SEQUENCE_ID expected=%0d got=%0d",channels_seen+row,packet_channels[row*16+:16]);
        channels_seen+=int'(packet_count);packets_seen++;
        if(packet_last) done=1;
      end
    end
  end
endmodule
