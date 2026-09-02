// Codex / Claude usage widget for iOS (Scriptable: https://scriptable.app)
//
// One script, one small home-screen widget per service. Paste this into a
// Scriptable script, then add two small widgets pointing at it; on each
// one, long-press > Edit Widget > Parameter, and set it to "codex" or
// "claude".
//
// Setup:
//   1. Replace URL below with the server's public endpoint.
//   2. Run set-agent-usage-widget-key.js once to store the API key in Keychain.

const URL = "https://usage.example.com/agent-usage-status.json";
const KEYCHAIN_ID = "agent-usage-widget-api-key";

const PAD = 14;
const BAR_W = 140;
const BAR_H = 11;

// Key is read from Keychain, not stored in this file.
function getApiKey() {
  return Keychain.contains(KEYCHAIN_ID) ? Keychain.get(KEYCHAIN_ID) : null;
}

async function fetchStatus(apiKey) {
  const req = new Request(URL);
  req.headers = { "X-Api-Key": apiKey };
  req.timeoutInterval = 10;
  return await req.loadJSON();
}

function fmtDuration(minutes) {
  if (minutes == null) return "--";
  const m = Math.max(0, Math.round(minutes));
  const totalHours = Math.floor(m / 60);
  const mm = m % 60;
  if (totalHours >= 24) {
    const d = Math.floor(totalHours / 24);
    const hh = totalHours % 24;
    return hh > 0 ? `${d}d ${hh}h` : `${d}d`;
  }
  return totalHours > 0 ? `${totalHours}h ${mm}m` : `${mm}m`;
}

// Recomputed from the absolute timestamp on every render, since the widget
// may refresh long after the server last wrote this value.
function minutesUntil(isoString) {
  if (!isoString) return null;
  const target = new Date(isoString).getTime();
  if (Number.isNaN(target)) return null;
  return (target - Date.now()) / 60000;
}

// Built from native WidgetStacks rather than a DrawContext image --
// Scriptable's custom-drawn images don't reliably render in the actual
// home-screen widget, even though they preview fine in-app.
function addBar(container, pct, w, h, fg, bg) {
  const track = container.addStack();
  track.layoutHorizontally();
  // WidgetStack has its own default padding; zero it or the fill renders
  // inset from the track's edges.
  track.setPadding(0, 0, 0, 0);
  track.spacing = 0;
  track.size = new Size(w, h);
  track.backgroundColor = bg;
  track.cornerRadius = h / 2;

  const fillW = Math.max(h, (Math.min(100, Math.max(0, pct)) / 100) * w);
  const fill = track.addStack();
  fill.setPadding(0, 0, 0, 0);
  fill.size = new Size(fillW, h);
  fill.backgroundColor = fg;
  fill.cornerRadius = h / 2;

  // A fixed-length trailing spacer keeps the fill left-anchored. A bare
  // addSpacer() (SwiftUI's Spacer()) has an implicit minimum length that
  // can shrink an already-full bar, so size it explicitly instead.
  track.addSpacer(Math.max(0, w - fillW));
}

function addWindow(container, label, win, fg, dim) {
  // The bar carries the signal; label/percent/reset are secondary detail,
  // kept small and dim so they don't compete with it.
  const remainingPct = win ? Math.max(0, Math.min(100, 100 - win.used_percent)) : null;
  addBar(container, remainingPct != null ? remainingPct : 0, BAR_W, BAR_H, fg, dim);

  container.addSpacer(4);
  const liveMinutes = win ? minutesUntil(win.resets_at) : null;
  const caption = container.addText(
    win ? `${label} · ${remainingPct}% · resets ${fmtDuration(liveMinutes)}` : "no data"
  );
  caption.font = Font.systemFont(10);
  caption.textColor = dim;
}

async function createWidget() {
  // Each home-screen instance is told which service to show via its widget
  // Parameter; defaults to codex for in-app preview runs where none is set.
  const service = (args.widgetParameter || "codex").trim().toLowerCase();

  const widget = new ListWidget();
  const fg = Color.dynamic(Color.black(), Color.white());
  const dim = Color.dynamic(new Color("#00000088"), new Color("#ffffff88"));
  widget.backgroundColor = Color.dynamic(Color.white(), Color.black());
  widget.setPadding(PAD, PAD, PAD, PAD);

  const apiKey = getApiKey();
  if (!apiKey) {
    const err = widget.addText("usage widget: no API key");
    err.font = Font.systemFont(11);
    err.textColor = fg;
    widget.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
    return widget;
  }

  let data;
  try {
    data = await fetchStatus(apiKey);
  } catch (e) {
    const err = widget.addText("usage widget: fetch failed");
    err.font = Font.systemFont(11);
    err.textColor = fg;
    widget.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
    return widget;
  }

  const svc = data[service];

  const header = widget.addText(service.toUpperCase());
  header.font = Font.semiboldSystemFont(14);
  header.textColor = fg;
  widget.addSpacer(20);

  if (!svc || !svc.ok) {
    const err = widget.addText("unavailable");
    err.font = Font.systemFont(11);
    err.textColor = dim;
  } else {
    addWindow(widget, "5H", svc.primary, fg, dim);
    widget.addSpacer(17);
    addWindow(widget, "7D", svc.secondary, fg, dim);
  }

  widget.refreshAfterDate = new Date(Date.now() + 10 * 60 * 1000);
  return widget;
}

const widget = await createWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
} else {
  await widget.presentSmall();
}
Script.complete();
