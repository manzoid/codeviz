# x86-64 Linux "hello, world" — freestanding (no libc), AT&T syntax.
# Writes to stdout via the write(2) syscall, then exits via exit(2).
.section .rodata
msg:
    .ascii "hello, world\n"
    .equ  msglen, . - msg

.section .text
.globl _start
_start:
    movq  $1, %rax          # syscall number: write
    movq  $1, %rdi          # fd 1 = stdout
    leaq  msg(%rip), %rsi   # buffer address
    movq  $msglen, %rdx     # byte count
    syscall                 # write(1, msg, msglen)

    movq  $60, %rax         # syscall number: exit
    xorq  %rdi, %rdi        # status 0
    syscall                 # exit(0)
