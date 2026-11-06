// The home's tour video: a clean poster with one button; the player's own
// controls appear once it plays.
document$.subscribe(() => {
  const frame = document.querySelector(".cv-frame");
  if (!frame) return;
  const video = frame.querySelector("video"), play = frame.querySelector(".cv-play");
  play.addEventListener("click", () => { video.controls = true; video.play(); });
  video.addEventListener("play", () => { video.controls = true; frame.classList.add("is-playing"); });
});
