`timescale 1ns/1ps
module tri_oracle_learned_margin_observer (
  input logic clk,rst_n,
  input logic [587:0] requests,
  input logic [159:0] responses,
  input logic [383:0] gate_totals,up_totals,
  input logic [47:0] outlier_totals
);
  always @(posedge clk)if(rst_n)begin
    for(int core=0;core<4;core++)if(requests[147*core+146] && responses[40*core+39] && requests[147*core+145])begin
      int token,group,count,channel,gate_margin,up_margin;
      token=int'($root.tri_oracle_trained_row_learned_tb.dut.prediction_token);
      group=int'($root.tri_oracle_trained_row_learned_tb.dut.prediction_group);
      count=int'(outlier_totals[12*core+:12]);
      if($isunknown({token,group,outlier_totals[12*core+:12],gate_totals[96*core+:96],up_totals[96*core+:96]}))
        $fatal(1,"LEARNED_UNKNOWN_CORE_MARGIN");
      if(token<0 || token>=2 || group<0 || group>=176 ||
         count!=int'($root.tri_oracle_trained_row_learned_tb.fixture_outlier_counts[token]) ||
         int'($root.tri_oracle_trained_row_learned_tb.strip_request[533:531])!=group%5)
        $fatal(1,"LEARNED_CORE_MARGIN_DESCRIPTOR");
      for(int lane=0;lane<8;lane++)begin
        channel=group*32+core*8+lane;
        gate_margin=2*int'(gate_totals[(core*8+lane)*12+:12])-count;
        up_margin=2*int'(up_totals[(core*8+lane)*12+:12])-count;
        if(gate_margin!=int'($signed($root.tri_oracle_trained_row_learned_tb.fixture_gate_margin[token*5632+channel])) ||
           up_margin!=int'($signed($root.tri_oracle_trained_row_learned_tb.fixture_up_margin[token*5632+channel])))
          $fatal(1,"LEARNED_CORE_EXACT_MARGIN token=%0d group=%0d channel=%0d",token,group,channel);
        $root.tri_oracle_trained_row_learned_tb.exact_margin_values+=2;
      end
    end
  end
endmodule
bind tri_oracle_sram_compute_cluster tri_oracle_learned_margin_observer margin_observer (
  .clk(clk),.rst_n(strip_rst_n),.requests(core_strip_requests),.responses(core_strip_responses),
  .gate_totals({cores[3].strip.predict.estimates[7].gate_total,cores[3].strip.predict.estimates[6].gate_total,cores[3].strip.predict.estimates[5].gate_total,cores[3].strip.predict.estimates[4].gate_total,cores[3].strip.predict.estimates[3].gate_total,cores[3].strip.predict.estimates[2].gate_total,cores[3].strip.predict.estimates[1].gate_total,cores[3].strip.predict.estimates[0].gate_total,cores[2].strip.predict.estimates[7].gate_total,cores[2].strip.predict.estimates[6].gate_total,cores[2].strip.predict.estimates[5].gate_total,cores[2].strip.predict.estimates[4].gate_total,cores[2].strip.predict.estimates[3].gate_total,cores[2].strip.predict.estimates[2].gate_total,cores[2].strip.predict.estimates[1].gate_total,cores[2].strip.predict.estimates[0].gate_total,cores[1].strip.predict.estimates[7].gate_total,cores[1].strip.predict.estimates[6].gate_total,cores[1].strip.predict.estimates[5].gate_total,cores[1].strip.predict.estimates[4].gate_total,cores[1].strip.predict.estimates[3].gate_total,cores[1].strip.predict.estimates[2].gate_total,cores[1].strip.predict.estimates[1].gate_total,cores[1].strip.predict.estimates[0].gate_total,cores[0].strip.predict.estimates[7].gate_total,cores[0].strip.predict.estimates[6].gate_total,cores[0].strip.predict.estimates[5].gate_total,cores[0].strip.predict.estimates[4].gate_total,cores[0].strip.predict.estimates[3].gate_total,cores[0].strip.predict.estimates[2].gate_total,cores[0].strip.predict.estimates[1].gate_total,cores[0].strip.predict.estimates[0].gate_total}),.up_totals({cores[3].strip.predict.estimates[7].up_total,cores[3].strip.predict.estimates[6].up_total,cores[3].strip.predict.estimates[5].up_total,cores[3].strip.predict.estimates[4].up_total,cores[3].strip.predict.estimates[3].up_total,cores[3].strip.predict.estimates[2].up_total,cores[3].strip.predict.estimates[1].up_total,cores[3].strip.predict.estimates[0].up_total,cores[2].strip.predict.estimates[7].up_total,cores[2].strip.predict.estimates[6].up_total,cores[2].strip.predict.estimates[5].up_total,cores[2].strip.predict.estimates[4].up_total,cores[2].strip.predict.estimates[3].up_total,cores[2].strip.predict.estimates[2].up_total,cores[2].strip.predict.estimates[1].up_total,cores[2].strip.predict.estimates[0].up_total,cores[1].strip.predict.estimates[7].up_total,cores[1].strip.predict.estimates[6].up_total,cores[1].strip.predict.estimates[5].up_total,cores[1].strip.predict.estimates[4].up_total,cores[1].strip.predict.estimates[3].up_total,cores[1].strip.predict.estimates[2].up_total,cores[1].strip.predict.estimates[1].up_total,cores[1].strip.predict.estimates[0].up_total,cores[0].strip.predict.estimates[7].up_total,cores[0].strip.predict.estimates[6].up_total,cores[0].strip.predict.estimates[5].up_total,cores[0].strip.predict.estimates[4].up_total,cores[0].strip.predict.estimates[3].up_total,cores[0].strip.predict.estimates[2].up_total,cores[0].strip.predict.estimates[1].up_total,cores[0].strip.predict.estimates[0].up_total}),.outlier_totals({cores[3].strip.predict.next_outliers,cores[2].strip.predict.next_outliers,cores[1].strip.predict.next_outliers,cores[0].strip.predict.next_outliers})
);
