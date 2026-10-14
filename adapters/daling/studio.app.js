/* Daling 을 디자인 스튜디오에 알려 주는 스크립트 (앱 화면 안에서 studio.js 보다 먼저 돈다).
   함수들은 스튜디오가 필요할 때 부르므로, 앱 전역(state·switchView·applyTheme …)이 아직 없어도 된다. */
window.__STUDIO_APP__ = {
  views: {
    dashboard: "대시보드", deadlines: "마감", calendar: "캘린더", courses: "과목", files: "자료",
    emails: "메일함", storage: "서랍", settings: "설정",
  },
  // 기본 테마는 data-theme 이 없는 상태다
  themes: [
    { key: "claude", label: "기본", selector: ":root:not([data-theme])" },
    { key: "light", label: "화이트", selector: ':root[data-theme="light"]' },
    { key: "navy", label: "남색", selector: ':root[data-theme="navy"]' },
    { key: "dark", label: "다크", selector: ':root[data-theme="dark"]' },
  ],
  darkThemes: ["dark"],
  tokens: [
    ["바탕", [["--bg", "화면 바탕"], ["--bg-deep", "깊은 바탕"], ["--surface", "카드"], ["--surface-soft", "옅은 카드"]]],
    ["선", [["--border", "선"], ["--border-strong", "진한 선"]]],
    ["글자", [["--text", "글자"], ["--text-soft", "흐린 글자"], ["--text-faint", "더 흐린 글자"]]],
    ["강조", [["--accent", "강조"], ["--accent-strong", "진한 강조"], ["--accent-soft", "옅은 강조"]]],
    ["상태", [
      ["--green", "초록"], ["--green-soft", "옅은 초록"], ["--amber", "노랑"], ["--amber-soft", "옅은 노랑"],
      ["--red", "빨강"], ["--red-soft", "옅은 빨강"], ["--blue", "파랑"], ["--blue-soft", "옅은 파랑"],
      ["--violet", "보라"], ["--violet-soft", "옅은 보라"],
    ]],
    ["로고", [["--bp-bg", "로고 바탕"], ["--bp-body", "로고 몸통"], ["--bp-hi", "로고 밝은 곳"], ["--bp-line", "로고 선"]]],
  ],
  sizeTokens: [["--radius", "큰 모서리", 0, 32], ["--radius-sm", "작은 모서리", 0, 24]],
  shadowToken: "--shadow",
  accent: { main: "--accent", strong: "--accent-strong", soft: "--accent-soft", surface: "--surface" },

  currentView() {
    return (typeof state !== "undefined" && state.view) || "dashboard";
  },
  switchView(view) {
    if (typeof switchView === "function") switchView(view);
  },
  currentTheme() {
    return document.documentElement.dataset.theme || "claude";
  },
  applyTheme(key) {
    // 앱 함수로 바꿔야 로고·차트 색까지 함께 바뀐다. 저장(save)은 하지 않는다.
    if (typeof applyTheme === "function") return applyTheme(key, { save: false });
    if (key === "claude") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.dataset.theme = key;
  },
  toast(text) {
    if (typeof showToast === "function") showToast(text);
  },
  get dialog() {
    return typeof appDialog === "function" ? (opts) => appDialog(opts) : null;
  },
  // 첫 화면을 다 그린 뒤에 저장본을 불러와야 글자·순서 변경이 제자리를 찾는다
  async ready() {
    for (let i = 0; i < 40 && !document.querySelector(".nav-item.active"); i++) await new Promise((r) => setTimeout(r, 100));
    await new Promise((r) => setTimeout(r, 400));
  },
};
