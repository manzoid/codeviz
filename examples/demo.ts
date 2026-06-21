function greet(name: string): string {
  const msg: string = "Hi, " + name;
  return msg;
}
let people: string[] = ["Tim", "Takumi"];
let out: string = greet(people[0]);
console.log(out);
