# Count DOWN from 5 to 1, PRINTING each value — watch %rbx fall while the
# program-output panel fills line by line ("5\n4\n3\n2\n1\n").
#
# Note: the counter lives in %rbx, not %rcx. The `syscall` instruction itself
# clobbers %rcx (and %r11) on x86-64 Linux, so a loop that makes a syscall each
# iteration must keep its counter in a register syscall leaves alone.
.section .data
buf:    .byte 0, 10              # [ digit, '\n' ] — we overwrite buf[0] each pass

.section .text
.globl _start
_start:
    movq  $5, %rbx              # counter = 5  (callee-saved; survives syscall)
print_loop:
    movq  %rbx, %rax
    addq  $48, %rax             # counter + '0'  -> ASCII digit
    movb  %al, buf(%rip)        # store the digit into buf[0]

    movq  $1, %rax              # syscall: write
    movq  $1, %rdi              # fd 1 = stdout
    leaq  buf(%rip), %rsi       # buffer
    movq  $2, %rdx              # 2 bytes: digit + newline
    syscall                     # write(1, buf, 2)  -- clobbers %rcx, %r11

    decq  %rbx                  # counter-- (sets ZF when it reaches 0)
    jnz   print_loop            # repeat while counter != 0

    movq  $60, %rax             # syscall: exit
    xorq  %rdi, %rdi            # status 0
    syscall
