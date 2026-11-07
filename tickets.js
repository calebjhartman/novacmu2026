#!/usr/bin/env node
// Local ticketing system for the DoorDash (NOVA) project.
// Zero dependencies. One Markdown file per ticket in ./tickets/, so tickets
// diff cleanly in git and both people and AI agents can read them.
//
// Usage: node tickets.js <command> [args]   (run with no args for help)

const fs = require("fs");
const path = require("path");

const DIR = path.join(__dirname, "tickets");
const STATUSES = ["todo", "in-progress", "blocked", "review", "done"];
const PRIORITIES = ["p0", "p1", "p2", "p3"];
const FIELDS = ["id", "title", "status", "priority", "assignee", "labels", "created", "updated"];

// ---------- storage ----------

function ensureDir() {
  if (!fs.existsSync(DIR)) fs.mkdirSync(DIR, { recursive: true });
}

function fileFor(id) {
  return path.join(DIR, `${id}.md`);
}

function parse(text) {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!m) throw new Error("ticket file is missing its --- header");
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const i = line.indexOf(":");
    if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return { ...meta, body: m[2] };
}

function serialize(t) {
  const head = FIELDS.map((k) => `${k}: ${t[k] ?? ""}`).join("\n");
  return `---\n${head}\n---\n${t.body || ""}`;
}

function load(id) {
  id = normalizeId(id);
  const f = fileFor(id);
  if (!fs.existsSync(f)) die(`No ticket ${id}`);
  return parse(fs.readFileSync(f, "utf8"));
}

function save(t) {
  ensureDir();
  t.updated = now();
  fs.writeFileSync(fileFor(t.id), serialize(t));
}

function all() {
  ensureDir();
  return fs
    .readdirSync(DIR)
    .filter((f) => /^T-\d+\.md$/.test(f))
    .map((f) => parse(fs.readFileSync(path.join(DIR, f), "utf8")))
    .sort((a, b) => num(a.id) - num(b.id));
}

function nextId() {
  const max = all().reduce((m, t) => Math.max(m, num(t.id)), 0);
  return `T-${String(max + 1).padStart(3, "0")}`;
}

// ---------- helpers ----------

const now = () => {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const num = (id) => parseInt(String(id).replace(/\D/g, ""), 10) || 0;

function normalizeId(id) {
  if (!id) die("Missing ticket id (e.g. T-001 or 1)");
  return `T-${String(num(id)).padStart(3, "0")}`;
}

function die(msg) {
  console.error(`error: ${msg}`);
  process.exit(1);
}

// Splits argv into positional words and --flag value pairs.
function parseArgs(argv) {
  const pos = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
      flags[key] = val;
    } else pos.push(a);
  }
  return { pos, flags };
}

function check(value, allowed, name) {
  if (value && !allowed.includes(value)) die(`${name} must be one of: ${allowed.join(", ")}`);
}

function appendLog(t, line) {
  const entry = `- ${now()} ${line}`;
  if (!/\n## Log\n/.test("\n" + t.body)) t.body = `${t.body.trimEnd()}\n\n## Log\n`;
  t.body = `${t.body.trimEnd()}\n${entry}\n`;
}

const rank = (t) =>
  PRIORITIES.indexOf(t.priority) * 1000 + num(t.id); // lower = more urgent

function row(t) {
  return [
    t.id.padEnd(6),
    t.status.padEnd(12),
    t.priority.padEnd(3),
    (t.assignee || "-").padEnd(12),
    t.title,
    t.labels ? `  [${t.labels}]` : "",
  ].join(" ");
}

// ---------- commands ----------

const commands = {
  new(pos, f) {
    const title = pos.join(" ").trim();
    if (!title) die('Usage: new "Title" [--priority p2] [--labels a,b] [--assignee who] [--body "..."]');
    check(f.priority, PRIORITIES, "priority");
    const t = {
      id: nextId(),
      title,
      status: "todo",
      priority: f.priority || "p2",
      assignee: f.assignee && f.assignee !== true ? f.assignee : "",
      labels: f.labels && f.labels !== true ? f.labels : "",
      created: now(),
      body:
        `\n## Description\n${f.body && f.body !== true ? f.body : "(describe the task)"}\n\n` +
        `## Acceptance criteria\n- [ ] \n\n## Log\n- ${now()} created\n`,
    };
    save(t);
    console.log(`Created ${t.id}: ${t.title}  ->  tickets/${t.id}.md`);
  },

  list(pos, f) {
    let ts = all();
    if (!f.all) ts = ts.filter((t) => t.status !== "done");
    if (f.status) ts = ts.filter((t) => t.status === f.status);
    if (f.assignee) ts = ts.filter((t) => t.assignee === f.assignee);
    if (f.label) ts = ts.filter((t) => t.labels.split(",").map((s) => s.trim()).includes(f.label));
    if (!ts.length) return console.log("No tickets.");
    console.log("ID     STATUS       PRI ASSIGNEE     TITLE");
    ts.forEach((t) => console.log(row(t)));
  },

  show(pos) {
    const t = load(pos[0]);
    console.log(serialize(t));
  },

  // Highest-priority unassigned todo ticket: what an agent should pick up next.
  next(pos, f) {
    const ts = all()
      .filter((t) => t.status === "todo" && (!t.assignee || t.assignee === f.assignee))
      .sort((a, b) => rank(a) - rank(b));
    if (!ts.length) return console.log("Nothing to pick up.");
    console.log(serialize(ts[0]));
  },

  claim(pos, f) {
    const who = f.as || pos[1];
    if (!who || who === true) die("Usage: claim <id> --as <name>");
    const t = load(pos[0]);
    if (t.assignee && t.assignee !== who && !f.force)
      die(`${t.id} is already claimed by ${t.assignee} (use --force to take it)`);
    t.assignee = who;
    t.status = "in-progress";
    appendLog(t, `claimed by ${who}`);
    save(t);
    console.log(`${t.id} -> in-progress (${who})`);
  },

  status(pos) {
    const [id, status, ...note] = pos;
    check(status, STATUSES, "status");
    if (!status) die(`Usage: status <id> <${STATUSES.join("|")}> [note]`);
    const t = load(id);
    const from = t.status;
    t.status = status;
    appendLog(t, `${from} -> ${status}${note.length ? `: ${note.join(" ")}` : ""}`);
    save(t);
    console.log(`${t.id}: ${from} -> ${status}`);
  },

  note(pos) {
    const [id, ...text] = pos;
    if (!text.length) die('Usage: note <id> "what happened"');
    const t = load(id);
    appendLog(t, text.join(" "));
    save(t);
    console.log(`Noted on ${t.id}`);
  },

  done(pos) {
    const [id, ...note] = pos;
    commands.status([id, "done", ...note]);
  },

  edit(pos, f) {
    const t = load(pos[0]);
    check(f.priority, PRIORITIES, "priority");
    for (const k of ["title", "priority", "assignee", "labels"]) if (typeof f[k] === "string") t[k] = f[k];
    if (f.unassign) t.assignee = "";
    appendLog(t, "edited");
    save(t);
    console.log(`Updated ${t.id}`);
  },

  board() {
    const ts = all();
    for (const s of STATUSES) {
      const group = ts.filter((t) => t.status === s);
      console.log(`\n== ${s.toUpperCase()} (${group.length}) ==`);
      group.sort((a, b) => rank(a) - rank(b)).forEach((t) => console.log("  " + row(t)));
    }
  },

  help() {
    console.log(`Local tickets for the DoorDash project  (files in tickets/)

  node tickets.js new "Title" [--priority p0-p3] [--labels a,b] [--assignee who] [--body "..."]
  node tickets.js list [--all] [--status s] [--assignee who] [--label l]
  node tickets.js board                     tickets grouped by status
  node tickets.js show <id>
  node tickets.js next [--assignee who]     highest-priority open todo ticket
  node tickets.js claim <id> --as <who>     assign + set in-progress
  node tickets.js status <id> <status> [note]   ${STATUSES.join(" | ")}
  node tickets.js note <id> "text"          append to the ticket's log
  node tickets.js done <id> [note]
  node tickets.js edit <id> [--title t] [--priority p] [--labels l] [--assignee who] [--unassign]

Ids can be written T-001 or just 1.`);
  },
};

// ---------- main ----------

const [cmd, ...rest] = process.argv.slice(2);
const { pos, flags } = parseArgs(rest);
(commands[cmd] || commands.help)(pos, flags);
