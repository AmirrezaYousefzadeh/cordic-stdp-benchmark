`timescale 1ns/1ps
// tb_pipe.v: testbench of the single-cycle (lut) and unrolled (cordic_unrolled, bitprod_unrolled, pow2) units.
//
// Compile with -DDUT=<module> -DNB=<input bits> -DFO=<Fo> -DLAT=<latency in cycles> -DNV=<number of vectors>
// -DVEC=\"<vector file>\". Vector file (tb/vec/<module>.hex, written by rtl/gen_units.py from the golden model):
// one hex word per line, {n[NB-1:0], y[FO:0]}.
//
// Checks, every cycle after reset:
//   - out_valid equals in_valid of LAT cycles earlier (so the latency is exactly LAT and nothing is lost or extra);
//   - y equals the vector's y whenever out_valid = 1 (bit-exact, 4-state compare);
//   - y does not change while out_valid = 0 (the unit holds its output).
// Phase A applies all vectors back to back in order (one input per cycle); phase B applies all vectors again in a
// pseudo-random order with random idle cycles, during which n is random and in_valid = 0. During reset in_valid = 1
// with random n: out_valid must stay 0.
// Ends with "PASS ..." or "FAIL ..." and returns exit status 0 or 1 from vvp.
module tb_pipe;
  localparam integer NB  = `NB;
  localparam integer FO  = `FO;
  localparam integer LAT = `LAT;
  localparam integer NV  = `NV;

  reg           clk      = 1'b0;
  reg           rst_n    = 1'b0;
  reg           in_valid = 1'b0;
  reg  [NB-1:0] n        = {NB{1'b0}};
  wire          out_valid;
  wire [FO:0]   y;

  `DUT dut (.clk(clk), .rst_n(rst_n), .in_valid(in_valid), .n(n), .out_valid(out_valid), .y(y));

  always #5 clk = ~clk;

  reg  [NB+FO:0] vec [0:NV-1];
  // scoreboard: entry j holds what was applied j cycles ago (j = 1 .. LAT)
  reg            sv [1:LAT];
  reg  [FO:0]    sy [1:LAT];
  reg  [NB-1:0]  sn [1:LAT];
  reg  [FO:0]    y_prev;
  reg            hold_on;
  integer errors, checked, cycles, i, j, k, seed, idx, nidle;

  task report_error(input [255:0] what);
    begin
      errors = errors + 1;
      if (errors <= 10)
        $display("ERROR cycle %0d: %0s: n=%0d expected out_valid=%b y=%0d, got out_valid=%b y=%0d",
                 cycles, what, sn[LAT], sv[LAT], sy[LAT], out_valid, y);
    end
  endtask

  // one cycle: apply the inputs of this cycle at the negedge, then check the outputs at the next negedge
  task tick(input v, input [NB-1:0] nn, input [FO:0] ye);
    begin
      for (j = LAT; j > 1; j = j - 1) begin
        sv[j] = sv[j-1];
        sy[j] = sy[j-1];
        sn[j] = sn[j-1];
      end
      sv[1] = v;
      sy[1] = ye;
      sn[1] = nn;
      in_valid = v;
      n = nn;
      @(negedge clk);
      cycles = cycles + 1;
      if (out_valid !== sv[LAT])
        report_error("out_valid");
      else if (sv[LAT]) begin
        checked = checked + 1;
        if (y !== sy[LAT]) report_error("y");
      end else if (hold_on && y !== y_prev)
        report_error("y changed while out_valid = 0");
      if (out_valid === 1'b1) hold_on = 1'b1;
      y_prev = y;
    end
  endtask

  initial begin
    errors = 0;
    checked = 0;
    cycles = 0;
    hold_on = 1'b0;
    seed = 20261113;
    for (j = 1; j <= LAT; j = j + 1) begin
      sv[j] = 1'b0;
      sy[j] = {(FO+1){1'b0}};
      sn[j] = {NB{1'b0}};
    end
    $readmemh(`VEC, vec);
    // reset with in_valid = 1: no output may appear
    rst_n = 1'b0;
    in_valid = 1'b1;
    n = $random(seed);
    for (k = 0; k < 4; k = k + 1) begin
      @(negedge clk);
      if (out_valid !== 1'b0) begin
        errors = errors + 1;
        $display("ERROR: out_valid = %b during reset", out_valid);
      end
      n = $random(seed);
    end
    rst_n = 1'b1;
    // phase A: all vectors back to back
    for (i = 0; i < NV; i = i + 1)
      tick(1'b1, vec[i][NB+FO:FO+1], vec[i][FO:0]);
    // phase B: all vectors in a pseudo-random order (odd multiplier: a permutation for NV = 2^NB), random idles
    for (i = 0; i < NV; i = i + 1) begin
      idx = (i * 37 + 11) % NV;
      if (({$random(seed)} % 4) == 0) begin
        nidle = 1 + ({$random(seed)} % 3);
        for (k = 0; k < nidle; k = k + 1)
          tick(1'b0, $random(seed), {(FO+1){1'b0}});
      end
      tick(1'b1, vec[idx][NB+FO:FO+1], vec[idx][FO:0]);
    end
    // drain
    for (k = 0; k < LAT + 2; k = k + 1)
      tick(1'b0, $random(seed), {(FO+1){1'b0}});
    if (errors == 0 && checked == 2 * NV)
      $display("PASS vectors=%0d results_checked=%0d latency=%0d cycles=%0d", NV, checked, LAT, cycles);
    else
      $display("FAIL errors=%0d results_checked=%0d (expected %0d)", errors, checked, 2 * NV);
    $finish_and_return((errors == 0 && checked == 2 * NV) ? 0 : 1);
  end
endmodule
