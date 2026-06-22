public class Alias {
  public static void main(String[] args) {
    int[] a = {10, 20};
    int[] b = a;          // b aliases the same array as a
    b[0] = 99;
    System.out.println(a[0]);
  }
}
