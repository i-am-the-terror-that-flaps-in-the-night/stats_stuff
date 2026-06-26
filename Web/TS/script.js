const button = document.getElementById("btn");
const title = document.getElementById("title");
const box = document.getElementById("box");

let toggled = false;

button.addEventListener("click", function () {
    toggled = !toggled
    rClicked = false
    
    // change text
    title.textContent = toggled ? "You clicked it 😏" : "Hello World";
    toggled = true
    // change box style
    if (toggled) {
        box.style.backgroundColor = "limegreen";
        box.style.transform = "rotate(45deg)";
    } else {
        box.style.backgroundColor = "tomato";
        box.style.transform = "rotate(0deg)";
    }
});