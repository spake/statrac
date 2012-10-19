$(document).ready(function(){
    cells = document.getElementsByClassName("score");
    for (i in cells) {
        cell = cells[i];
        contents = cell.textContent;
        score = parseInt(contents);
        if (isNaN(score)) {
            score = 0;
        }
        h = 0.3*Math.pow((score/100),2);
        s = 0.8;
        l = 0.6;
        rgb = hslToRgb(h, s, l);
        colour = '#'+decimalToHex(rgb[0])+decimalToHex(rgb[1])+decimalToHex(rgb[2]);
        if (cell.style != undefined) {
            cell.style.backgroundColor = colour;
        }
    }
});
