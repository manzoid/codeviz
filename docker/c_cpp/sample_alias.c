#include <stdio.h>

struct Point {
  int x;
  int y;
};

int main() {
  struct Point p = {3, 4};
  struct Point *a = &p;   /* a and b point at the SAME struct */
  struct Point *b = &p;
  a->x = 100;             /* mutation visible through b too */
  printf("b->x = %d\n", b->x);
  return 0;
}
