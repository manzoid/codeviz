# Count UP from 0 to 3, then exit with the counter as the status code.
# Watch %rcx climb, and the flags after `cmp`: `jl` is taken while rcx < limit
# (SF != OF), then falls through once rcx reaches the limit.
.section .text
.globl _start
_start:
    movq  $0, %rcx          # counter = 0
    movq  $3, %rbx          # limit   = 3
loop:
    incq  %rcx              # counter++
    cmpq  %rbx, %rcx        # compare counter with limit (sets flags)
    jl    loop              # if counter < limit, repeat
    movq  $60, %rax         # syscall: exit
    movq  %rcx, %rdi        # status = counter
    syscall
