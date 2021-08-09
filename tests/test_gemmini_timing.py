from __future__ import annotations

#from ctypes import *
#import os
#import subprocess
#import numpy as np
#import scipy.stats as st
#import os

import os
import sys
_HERE_ = os.path.dirname(os.path.abspath(__file__))
print(sys.path[0])
sys.path.append(sys.path[0]+"/..")
sys.path.append(sys.path[0]+"/.")
from SYS_ATL import proc, instr, Procedure, DRAM, compile_procs
from SYS_ATL.libs.memories import GEMM_SCRATCH, GEMM_ACCUM, MDRAM
from .gemmini import *
from .harness_gemmini import ENV, GemmTestBuilder
import pytest


# --------------------------------------------------------------------------- #
#   MatMul Demo
# --------------------------------------------------------------------------- #

@pytest.mark.skip()
def test_matmul_demo():
  T = GemmTestBuilder('matmul_demo')
  do_init(T)

  NN = 64
  MM = 64
  KK = 64

  T.alloc_dram_2i8('x', NN, KK, '1')
  T.alloc_dram_2i8('y', KK, MM, '1')
  T.alloc_dram_2i8('z', NN, MM, '0')


  @proc
  def matmul2d(
    N : size, M : size, K : size,
    A : i8[N,K] @ DRAM,
    B : i8[K,M] @ DRAM,
    C : i8[N,M] @ DRAM,
  ):
    for i in par(0,N):
      for j in par(0,M):
        C[i,j] = 0.0
        for k in par(0,K):
          C[i,j] += A[i,k]*B[k,j]


  matmul2d = matmul2d.partial_eval(NN, MM, KK)

  matmul2d = (matmul2d.split('k',16,['k','k_in'], perfect=True)
                      .split('j',16,['j','j_in'], perfect=True)
                      .split('i',16,['i','i_in'], perfect=True))

  matmul2d = (matmul2d.reorder('i_in','j')
                      .fission_after('C[_] = 0.0', n_lifts=2)
                      .reorder('j_in #1','k')
                      .reorder('i_in #1','k'))

  matmul2d = pre_bake_stage_C(matmul2d, "for i_in in _: _\n"+
                                        "for k in _: _", 'C', 'CG')

  matmul2d = pre_bake_stage_A_and_B(matmul2d)

  matmul2d = pre_bake_abstract_A(matmul2d, 'for i_in in _: _ #1', ld_i8)

  matmul2d = pre_bake_abstract_BC_and_mmul(matmul2d)

  matmul2d = matmul2d.set_precision('CG','i32')

  matmul2d = (matmul2d.set_memory('CG',GEMM_ACCUM)
                      .set_memory('BG',GEMM_SCRATCH)
                      .set_memory('AG',GEMM_SCRATCH))

  matmul2d = (matmul2d.lift_alloc('AG : _')
                      .lift_alloc('BG : _'))

  matmul2d = (matmul2d.lift_alloc('AG : _', n_lifts=2)
                      .lift_alloc('BG : _', n_lifts=2)
                      .lift_alloc('CG : _', n_lifts=2))


  matmul2d = (matmul2d.unroll('k'))
  
  matmul2d = (matmul2d.unroll('j').unroll('i'))

  orig_matmul = matmul2d  

  print()
  print(matmul2d)
  T.add_proc(matmul2d)

  T.start_timer('gemmini')
  T.add_body([f'matmul2d(x, y, z);',
              f'gemmini_fence();',
              f''])
  T.stop_timer('gemmini', 'Instruction Count for GEMMINI version')
  
  T.compile().run()



def pre_bake_stage_C(p, pattern, name_in, name='CG'):
  @proc
  def matmul2d(
    A: i8[64, 64] @ DRAM,
    B: i8[64, 64] @ DRAM,
    C: i8[64, 64] @ DRAM
  ):
    for i in par(0, 4):
        for j in par(0, 4):
            CG : i8[16,16] @ MDRAM
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    CG[i_in,j_in] = 0.0
            for k in par(0, 4):
                for i_in in par(0, 16):
                    for j_in in par(0, 16):
                        for k_in in par(0, 16):
                            CG[i_in,j_in] += (
                                A[16 * i + i_in, 16 * k + k_in] *
                                B[16 * k + k_in, 16 * j + j_in] )
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    C[16 * i + i_in, 16 * j + j_in] = CG[i_in,j_in]
  return matmul2d


def pre_bake_stage_A_and_B(p):
  @proc
  def matmul2d(
    A: i8[64, 64] @ DRAM,
    B: i8[64, 64] @ DRAM,
    C: i8[64, 64] @ DRAM
  ):
    for i in par(0, 4):
        for j in par(0, 4):
            CG : i8[16,16] @ MDRAM
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    CG[i_in,j_in] = 0.0
            for k in par(0, 4):
                AG : i8[16,16] @ MDRAM
                BG : i8[16,16] @ MDRAM
                for i_in in par(0, 16):
                    for k_in in par(0, 16):
                        AG[i_in,k_in] = A[16 * i + i_in, 16 * k + k_in]
                for k_in in par(0, 16):
                    for j_in in par(0, 16):
                        BG[k_in,j_in] = B[16 * k + k_in, 16 * j + j_in]
                for i_in in par(0, 16):
                    for j_in in par(0, 16):
                        for k_in in par(0, 16):
                            CG[i_in,j_in] += AG[i_in,k_in] * BG[k_in,j_in]
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    C[16 * i + i_in, 16 * j + j_in] = CG[i_in,j_in]
  return matmul2d



def pre_bake_abstract_A(p, pattern, instr):
  @proc
  def matmul2d(
    A: i8[64, 64] @ DRAM,
    B: i8[64, 64] @ DRAM,
    C: i8[64, 64] @ DRAM
  ):
    for i in par(0, 4):
        for j in par(0, 4):
            CG : i8[16,16] @ MDRAM
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    CG[i_in,j_in] = 0.0
            for k in par(0, 4):
                AG : i8[16,16] @ MDRAM
                BG : i8[16,16] @ MDRAM
                scale : f32
                scale = 1.0
                ld_i8(16, 16, scale, A[16*i:16*i+16, 16*k:16*k+16], AG)
                for k_in in par(0, 16):
                    for j_in in par(0, 16):
                        BG[k_in,j_in] = B[16 * k + k_in, 16 * j + j_in]
                for i_in in par(0, 16):
                    for j_in in par(0, 16):
                        for k_in in par(0, 16):
                            CG[i_in,j_in] += AG[i_in,k_in] * BG[k_in,j_in]
            for i_in in par(0, 16):
                for j_in in par(0, 16):
                    C[16 * i + i_in, 16 * j + j_in] = CG[i_in,j_in]
  return matmul2d


def pre_bake_abstract_BC_and_mmul(p):
  @proc
  def matmul2d(
    A: i8[64, 64] @ DRAM,
    B: i8[64, 64] @ DRAM,
    C: i8[64, 64] @ DRAM
  ):
    scale : f32
    scale = 1.0
    for i in par(0, 4):
        for j in par(0, 4):
            CG : i8[16,16] @ MDRAM
            zero_acc_i32(16,16, CG)
            for k in par(0, 4):
                AG : i8[16,16] @ MDRAM
                BG : i8[16,16] @ MDRAM
                ld_i8(16, 16, scale, A[16*i:16*i+16, 16*k:16*k+16], AG)
                ld_i8(16, 16, scale, B[16*k:16*k+16, 16*j:16*j+16], BG)
                matmul_acc_i8(16,16,16, False, False, AG, BG, CG)
            st_acc_i8(16,16, scale, False, CG, C[16*i:16*i+16, 16*j:16*j+16])
  return matmul2d



def do_init(T):
  T.add_body(['gemm_init_mem();',
              'gemm_acc_init_mem();',
              'init_mem();',
              'gemmini_flush(0);',
              ''])

  T.add_proc(ld_i8)
  T.add_proc(ld_acc_i8)

  @proc
  def mdram_dummy():
    x : i8 @ MDRAM
  T.add_proc(mdram_dummy)



def test_matmul_c_i8():
  T = GemmTestBuilder('matmul_c_i8')
  T.add_body(['gemm_init_mem();',
              'gemm_acc_init_mem();',
              'gemmini_flush(0);',
              ''])
  T.add_body(["matmul_c_i8_lib_Context *ctxt;"])

  NN = 60
  MM = 70
  KK = 120

  T.alloc_dram_2i8('x', NN, KK, '1')
  T.alloc_dram_2i8('y', KK, MM, '1')
  T.alloc_dram_f32('a_scale', '3.0f')
  T.alloc_dram_f32('b_scale', '2.0f')
  T.alloc_dram_f32('c_scale', '2.0f')
  T.alloc_dram_2i8('z_cpu', NN, MM, '0') # expected result
  T.alloc_dram_2i8('z_gemmini', NN, MM, '0')

  @proc
  def matmul_c_i8(
    N : size,
    M : size,
    K : size,
    a_scale : f32,
    b_scale : f32,
    c_scale : f32,
    acc     : bool,
    trans_a : bool,
    trans_b : bool,
    A : [i8][N,K] @ DRAM,
    B : [i8][K,M] @ DRAM,
    C : [i8][N,M] @ DRAM,
  ):
    assert stride(A, 1) == 1
    assert stride(B, 1) == 1
    assert stride(C, 1) == 1

    for i in par(0,N):
        for j in par(0,M):
            res : i32 @ GEMM_ACCUM
            res = 0.0
            for k in par(0,K):
                tmp_a : f32
                tmp_a = A[i,k]
                tmp_a = tmp_a * a_scale
                a : i8 @ GEMM_SCRATCH
                a = tmp_a

                tmp_b : f32
                tmp_b = B[k,j]
                tmp_b = tmp_b * b_scale
                b : i8 @ GEMM_SCRATCH
                b = tmp_b

                a2 : i32
                b2 : i32
                a2 = a
                b2 = b
                res += a2*b2

            tmp_res : i8
            if acc == True:
                tmp_res = relu(res)
            else:
                tmp_res = res

            tmp_res2 : f32
            tmp_res2 = tmp_res
            tmp_res2 = tmp_res2 * c_scale
            clamp(tmp_res2, tmp_res)
            C[i,j] = tmp_res


  matmul_c_i8 = matmul_c_i8.split('i',128,['io','i'], tail='cut')
  matmul_c_i8 = matmul_c_i8.split('j',128,['jo','j'], tail='cut')
  matmul_c_i8 = matmul_c_i8.fission_after('for jo in _:_', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.reorder('i #1','jo')

# main block
  matmul_c_i8 = matmul_c_i8.split('i #1',16,['i','i_in'], perfect=True)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','j')
  matmul_c_i8 = matmul_c_i8.split('j #1',16,['j','j_in'], perfect=True)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #0', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #0', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','k')
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #1',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #0', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #1', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #0', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #1', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")
# main block basic tiling done


# next block
  matmul_c_i8 = matmul_c_i8.split('i #2',16,['i','i_in'], perfect=True)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','j')
  matmul_c_i8 = matmul_c_i8.split('j #2',16,['j','j_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #1', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #1', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #1', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #1', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','k')
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #2', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #2', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #2',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #2', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #3', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #2', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #3', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")

# if M % 128 % 16 > 0: block
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #2', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #2', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #2', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','k')
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #4', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #4', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #4', n_lifts=1, size=16)
  matmul_c_i8 = matmul_c_i8.split('k #3',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #4', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #5', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #4', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #5', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")

# next....
  matmul_c_i8 = matmul_c_i8.split('i #3',16,['i','i_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.fission_after('for jo in _:_ #1', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','jo')
  matmul_c_i8 = matmul_c_i8.split('j #3',16,['j','j_in'], perfect=True)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','j')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #3', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #3', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #3', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #3', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('j_in','k')
  matmul_c_i8 = matmul_c_i8.reorder('i_in','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #6', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #6', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #4',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #6', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #7', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #6', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #7', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")

# next..
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','j')
  matmul_c_i8 = matmul_c_i8.split('j #4',16,['j','j_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #4', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #4', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #4', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #4', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','k')
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #8', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #8', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #5',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #8', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #9', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #8', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #9', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")

# next!
  matmul_c_i8 = matmul_c_i8.reorder('j_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #5', n_lifts=1, size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #5', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #5', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('j_in','k')
  matmul_c_i8 = matmul_c_i8.reorder('i_in','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #10', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #10', n_lifts=2, size=16)
  matmul_c_i8 = matmul_c_i8.split('k #6',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #10', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #11', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #10', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #11', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")


# almost last!!
  matmul_c_i8 = matmul_c_i8.fission_after('for jo in _:_ #2', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.reorder('i_in','jo')
  matmul_c_i8 = matmul_c_i8.split('j #5',16,['j','j_in'], perfect=True)
  matmul_c_i8 = matmul_c_i8.reorder('i_in #1','j')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #6', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #6', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('j_in','k')
  matmul_c_i8 = matmul_c_i8.reorder('i_in','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #12', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #12', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #7',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #12', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #13', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #12', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #13', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")

# Last!
  matmul_c_i8 = matmul_c_i8.reorder('i_in','j')
  matmul_c_i8 = matmul_c_i8.split('j #6',16,['j','j_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.reorder('j_in','i_in')
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #7', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #7', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('j_in','k')
  matmul_c_i8 = matmul_c_i8.reorder('i_in','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #14', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #14', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.split('k #8',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #14', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #15', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #14', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #15', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")


#last!!!
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #8', n_lifts=1, size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('res : _ #8', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('res[_] = 0.0 #0', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.fission_after('for k in _:_ #8', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.reorder('j_in','k')
  matmul_c_i8 = matmul_c_i8.reorder('i_in','k')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #16', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #16', n_lifts=1, size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #16', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.split('k #9',16,['k','k_in'], tail='cut_and_guard')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #16', n_lifts=1, mode='col')
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : _ #17', n_lifts=1, mode='col', size=16)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #16', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : _ #17', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('a[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #0', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.fission_after('b[_] = _ #1', n_lifts=3)
  matmul_c_i8 = matmul_c_i8.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','i_in')
  matmul_c_i8 = matmul_c_i8.reorder('k_in #1','j_in')
  matmul_c_i8 = matmul_c_i8.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8 = matmul_c_i8.replace(st_acc_i8, "for i_in in _:_ #0")


 # Optimization
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8', n_lifts=2)
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #0', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #0', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('a : i8 #1', n_lifts=1)
  matmul_c_i8 = matmul_c_i8.lift_alloc('b : i8 #1', n_lifts=1)

  print(matmul_c_i8)
  T.add_proc(matmul_c_i8)
  T.start_timer('gemmini')
  T.add_body([f'matmul_c_i8(ctxt, {NN}, {MM}, {KK}, a_scale, b_scale, c_scale, false, true, false, (struct systl_win_2i8){{ x, {NN}, 1 }}, (struct systl_win_2i8){{ y, {KK}, 1 }}, (struct systl_win_2i8){{ z_cpu, {NN}, 1 }});',
              f'gemmini_fence();'])
  T.stop_timer('gemmini', 'Cycles for GEMMINI version')
  T.compile().run()

  # TODO: fix
  #matmul_c_i8.check_effects()

  print(matmul_c_i8)




@pytest.mark.skip()
def test_matmul_c_i8_perfect():
  T = GemmTestBuilder('matmul_c_i8_perfect')
  T.add_body(['gemm_init_mem();',
              'gemm_acc_init_mem();',
              'gemmini_flush(0);',
              ''])
  T.add_body(["matmul_c_i8_perfect_lib_Context *ctxt;"])

  NN = 512
  MM = 512
  KK = 512

  T.alloc_dram_2i8('x', NN, KK, '1')
  T.alloc_dram_2i8('y', KK, MM, '1')
  T.alloc_dram_f32('a_scale', '3.0f')
  T.alloc_dram_f32('b_scale', '2.0f')
  T.alloc_dram_f32('c_scale', '2.0f')
  T.alloc_dram_2i8('z_cpu', NN, MM, '0') # expected result
  T.alloc_dram_2i8('z_gemmini', NN, MM, '0')

  @proc
  def matmul_c_i8_perfect(
    N : size,
    M : size,
    K : size,
    a_scale : f32,
    b_scale : f32,
    c_scale : f32,
    acc     : bool,
    trans_a : bool,
    trans_b : bool,
    A : i8[N,K] @ DRAM,
    B : i8[K,M] @ DRAM,
    C : i8[N,M] @ DRAM,
  ):
    assert N == 512
    assert M == 512
    assert K == 512

    for i in par(0,512):
        for j in par(0,512):
            res : i32 @ GEMM_ACCUM
            res = 0.0
            for k in par(0,512):
                tmp_a : f32
                tmp_a = A[i,k]
                tmp_a = tmp_a * a_scale
                a : i8 @ GEMM_SCRATCH
                a = tmp_a

                tmp_b : f32
                tmp_b = B[k,j]
                tmp_b = tmp_b * b_scale
                b : i8 @ GEMM_SCRATCH
                b = tmp_b

                a2 : i32
                b2 : i32
                a2 = a
                b2 = b
                res += a2*b2

            tmp_res : i8
            if acc == True:
                tmp_res = relu(res)
            else:
                tmp_res = res

            tmp_res2 : f32
            tmp_res2 = tmp_res
            tmp_res2 = tmp_res2 * c_scale
            clamp(tmp_res2, tmp_res)
            C[i,j] = tmp_res

  matmul_c_i8_perfect = matmul_c_i8_perfect.split('i',128,['io','i'], perfect=True)
  matmul_c_i8_perfect = matmul_c_i8_perfect.split('j',128,['jo','j'], perfect=True)
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('i','jo')

  matmul_c_i8_perfect = matmul_c_i8_perfect.split('i',16,['i','i_in'], perfect=True)
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('i_in','j')
  matmul_c_i8_perfect = matmul_c_i8_perfect.split('j',16,['j','j_in'], perfect=True)

  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('res : _ #0', n_lifts=1)
  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('res : _ #0', n_lifts=1, mode='col', size=16)
  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('res : _ #0', n_lifts=2)
  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('res[_] = 0.0 #0', n_lifts=2)

  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('for k in _:_ #0', n_lifts=2)

  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('i_in','k')
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('j_in','k')

  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('a : i8', n_lifts=2)
  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('b : i8', n_lifts=2)

  matmul_c_i8_perfect = matmul_c_i8_perfect.split('k',16,['k','k_in'], perfect=True)

  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('a : _ #0', n_lifts=1, mode='col')
  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('b : _', n_lifts=1)

  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('a[_] = _', n_lifts=3)
  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('b[_] = _', n_lifts=3)

  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('j_in','i_in')
  matmul_c_i8_perfect = matmul_c_i8_perfect.replace(zero_acc_i32, "for i_in in _:_ #0")
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('k_in','i_in')
  matmul_c_i8_perfect = matmul_c_i8_perfect.replace(ld_i8, "for i_in in _:_ #0")
  matmul_c_i8_perfect = matmul_c_i8_perfect.replace(ld_i8, "for k_in in _:_ #0")
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('k_in','j_in')
  matmul_c_i8_perfect = matmul_c_i8_perfect.replace(matmul_acc_i8, "for i_in in _:_ #0")
  matmul_c_i8_perfect = matmul_c_i8_perfect.replace(st_acc_i8, "for i_in in _:_ #0")

  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('a : i8', n_lifts=3)
  matmul_c_i8_perfect = matmul_c_i8_perfect.lift_alloc('b : i8', n_lifts=3)

  # Real optimization
  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('zero_acc_i32(_)', n_lifts=2)
  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('for k in _:_', n_lifts=2)
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('j','k')
  matmul_c_i8_perfect = matmul_c_i8_perfect.reorder('i','k')
  matmul_c_i8_perfect = matmul_c_i8_perfect.fission_after('ld_i8(_)', n_lifts=2)

  matmul_c_i8_perfect = matmul_c_i8_perfect.unroll('j #1')
  matmul_c_i8_perfect = matmul_c_i8_perfect.unroll('i #2')
  matmul_c_i8_perfect = matmul_c_i8_perfect.unroll('j #1')
  matmul_c_i8_perfect = matmul_c_i8_perfect.unroll('j #1')
  matmul_c_i8_perfect = matmul_c_i8_perfect.unroll('j #1')


  T.add_proc(matmul_c_i8_perfect)

  T.start_timer('gemmini')
  T.add_body([f'matmul_c_i8_perfect(ctxt, {NN}, {MM}, {KK}, a_scale, b_scale, c_scale, false, true, false, x, y, z_cpu);',
              f'gemmini_fence();'])
  T.stop_timer('gemmini', 'Cycles for GEMMINI version')

  T.compile().run()

  print(matmul_c_i8_perfect)
  matmul_c_i8_perfect.check_effects()

