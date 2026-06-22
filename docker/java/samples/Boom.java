public class Boom {
  public static void main(String[] args) {
    int[] xs = {1, 2};
    int bad = xs[5];      // ArrayIndexOutOfBoundsException
    System.out.println(bad);
  }
}
