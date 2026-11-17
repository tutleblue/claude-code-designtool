const list = document.getElementById("list");
async function load() {
  const res = await fetch("/api/items").then((r) => r.json());
  list.innerHTML = res.items.map((it) => `<li class="item"><span class="name">${it.name}</span><span class="when">${it.when}</span></li>`).join("");
}
document.getElementById("addBtn").addEventListener("click", async () => {
  const res = await fetch("/api/items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "새 할 일" }) }).then((r) => r.json());
  document.querySelector(".hint").textContent = res.studio ? "스튜디오라 저장하지 않았어요." : "저장했어요.";
});
load();
