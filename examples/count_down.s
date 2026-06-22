# Count DOWN from 3 to 0, then exit. The contrast with count_up.s: this loop
# branches on the Zero Flag. `dec` sets ZF when %rcx reaches 0, and `jnz` falls
# through exactly then — watch ZF flip 0 -> 1 on the last decrement.
.section .text
.globl _start
_start:
    movq  $3, %rcx          # counter = 3
down:
    decq  %rcx              # counter-- (sets ZF when it hits 0)
    jnz   down              # repeat while counter != 0
    movq  $60, %rax         # syscall: exit
    xorq  %rdi, %rdi        # status 0
    syscall
