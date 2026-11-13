`timescale 1ns/1ps
// tb_trace.v: testbench of the shift-decay trace update (shiftdecay).
//
// Compile with -DDUT=<module> -DW=<W = Fo + guard> -DFO=<Fo> -DNV=<number of vectors> -DVEC=\"<vector file>\".
// Vector file: one hex word per line, {set, decay, y_new[W:0], y_out[FO:0]}, one line per cycle, from the golden
// model: y_new is the trace after this cycle's update (shift_decay_trace with fo = W, guard = 0, which returns the
// internal trace Y_t) and y_out is the output code of the trace before it (shift_decay_trace with fo = Fo, guard).
//
// The testbench plays the trace memory: it starts at 2^W (the model's Y_0), drives y_old from it, and writes
// y_new back after every cycle, so the unit runs through the whole trajectory exactly as in a learning engine.
// Ends with "PASS ..." or "FAIL ..." and returns exit status 0 or 1 from vvp.
module tb_trace;
  localparam integer W  = `W;
  localparam integer FO = `FO;
  localparam integer NV = `NV;

  reg          clk   = 1'b0;
  reg          rst_n = 1'b0;
  reg  [W:0]   y_old = {(W+1){1'b0}};
  reg          set_i = 1'b0;
  reg          dec_i = 1'b0;
  wire [W:0]   y_new;
  wire [FO:0]  y_out;

  `DUT dut (.clk(clk), .rst_n(rst_n), .y_old(y_old), .set(set_i), .decay(dec_i), .y_new(y_new), .y_out(y_out));

  always #5 clk = ~clk;

  reg  [W+FO+3:0] vec [0:NV-1];
  reg  [W:0]      mem;
  integer errors, checked, i, k;

  initial begin
    errors = 0;
    checked = 0;
    $readmemh(`VEC, vec);
    for (k = 0; k < 2; k = k + 1) @(negedge clk);
    rst_n = 1'b1;
    mem = {1'b1, {W{1'b0}}};
    for (i = 0; i < NV; i = i + 1) begin
      y_old = mem;
      set_i = vec[i][W+FO+3];
      dec_i = vec[i][W+FO+2];
      @(negedge clk);
      checked = checked + 1;
      if (y_new !== vec[i][W+FO+1:FO+1] || y_out !== vec[i][FO:0]) begin
        errors = errors + 1;
        if (errors <= 10)
          $display("ERROR cycle %0d: set=%b decay=%b y_old=%0d: expected y_new=%0d y_out=%0d, got y_new=%0d y_out=%0d",
                   i, set_i, dec_i, y_old, vec[i][W+FO+1:FO+1], vec[i][FO:0], y_new, y_out);
      end
      mem = y_new;
    end
    if (errors == 0 && checked == NV)
      $display("PASS vectors=%0d results_checked=%0d latency=1 cycles=%0d", NV, checked, NV);
    else
      $display("FAIL errors=%0d results_checked=%0d (expected %0d)", errors, checked, NV);
    $finish_and_return((errors == 0 && checked == NV) ? 0 : 1);
  end
endmodule
