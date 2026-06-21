#include <stdio.h>
int sum(int n) {
  int total = 0;
  for (int i = 1; i <= n; i++) total += i;
  return total;
}
int main() {
  int arr[3] = {10, 20, 30};
  int s = sum(3);
  printf("%d\n", s + arr[0]);
  return 0;
}
