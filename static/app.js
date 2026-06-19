const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");

let state = "ask_num_players";
let gameId = null;
let numPlayers = 1;
let playerNames = [];
let currentNamingIndex = 0;
let gameFormat = "";
let constraint = "";
let pickCount = 0;
let pendingConfirm = null;
let currentTurnPlayer = "";

function addMsg(text, cls) {
    const div = document.createElement("div");
    div.className = `msg ${cls}`;
    div.innerHTML = text;
    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    const chat = document.getElementById("chat");
    requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

function showTyping() {
    const div = document.createElement("div");
    div.className = "msg typing-indicator cursor-blink";
    div.id = "typing";
    div.textContent = "processing";
    messagesEl.appendChild(div);
    scrollToBottom();
}

function hideTyping() {
    const el = document.getElementById("typing");
    if (el) el.remove();
}

function setInputEnabled(enabled) {
    inputEl.disabled = !enabled;
    sendBtn.disabled = !enabled;
    if (enabled) {
        inputEl.value = "";
        inputEl.focus();
    }
}

function botMsg(text) { return addMsg(text, "msg-bot"); }
function userMsg(text) { addMsg(text, "msg-user"); }
function statsMsg(text) { addMsg(text, "msg-stats"); }
function commentaryMsg(text) { addMsg(text, "msg-commentary"); }

// --- Setup flow ---

function startSetup() {
    const div = botMsg("CRICKET FANTASY DRAFT v1.0\n\nBuild your dream XI under a constraint — every pick counts.\n\nHow many players?");
    const opts = document.createElement("div");
    opts.className = "setup-options";
    [1, 2, 3, 4].forEach(n => {
        const btn = document.createElement("button");
        btn.textContent = n === 1 ? "1 (solo)" : `${n} players`;
        btn.onclick = () => { disableAllButtons(); handleNumPlayers(n); };
        opts.appendChild(btn);
    });
    div.appendChild(opts);
    setInputEnabled(false);
}

function disableAllButtons() {
    document.querySelectorAll(".setup-options button, .confirm-buttons button, .candidate-btn").forEach(b => {
        b.disabled = true;
        b.style.opacity = "0.5";
        b.style.cursor = "default";
    });
}

function handleNumPlayers(n) {
    numPlayers = n;
    userMsg(n === 1 ? "1 (solo)" : `${n} players`);
    playerNames = [];
    currentNamingIndex = 0;
    if (n === 1) {
        state = "ask_name";
        botMsg("What's your name?");
        inputEl.placeholder = "enter your name...";
        setInputEnabled(true);
    } else {
        state = "ask_name";
        botMsg(`${n} players — nice.\n\nPlayer 1, what's your name?`);
        inputEl.placeholder = "enter player 1's name...";
        setInputEnabled(true);
    }
}

function handleName(text) {
    const name = text.trim() || `Player ${currentNamingIndex + 1}`;
    playerNames.push(name);
    currentNamingIndex++;

    if (currentNamingIndex < numPlayers) {
        state = "ask_name";
        botMsg(`Welcome, <b>${name}</b>.\n\nPlayer ${currentNamingIndex + 1}, your name?`);
        inputEl.placeholder = `enter player ${currentNamingIndex + 1}'s name...`;
        setInputEnabled(true);
        return;
    }

    if (numPlayers === 1) {
        botMsg("Good to have you, <b>" + name + "</b>.");
    } else {
        botMsg("Welcome, <b>" + name + "</b>.\n\nAll players in: " + playerNames.map(n => `<b>${n}</b>`).join(", "));
    }

    state = "ask_format";
    const div = botMsg("Pick your format:");
    const opts = document.createElement("div");
    opts.className = "setup-options";
    ["Test", "ODI", "T20I"].forEach(fmt => {
        const btn = document.createElement("button");
        btn.textContent = fmt;
        btn.onclick = () => { disableAllButtons(); handleFormat(fmt); };
        opts.appendChild(btn);
    });
    div.appendChild(opts);
    setInputEnabled(false);
}

function handleFormat(fmt) {
    gameFormat = fmt;
    userMsg(fmt);
    state = "ask_constraint";
    const div = botMsg("How do you want your constraint?");
    const opts = document.createElement("div");
    opts.className = "setup-options";

    const randomBtn = document.createElement("button");
    randomBtn.textContent = "Random constraint (instant)";
    randomBtn.onclick = () => { disableAllButtons(); handleConstraintChoice("random"); };
    opts.appendChild(randomBtn);

    const customBtn = document.createElement("button");
    customBtn.textContent = "I have my own constraint";
    customBtn.onclick = () => { disableAllButtons(); handleConstraintChoice("custom"); };
    opts.appendChild(customBtn);

    div.appendChild(opts);
}

async function handleConstraintChoice(choice) {
    if (choice === "random") {
        userMsg("Random constraint");
        showTyping();
        const resp = await fetch("/api/reroll_constraint", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ format: gameFormat }),
        });
        const data = await resp.json();
        hideTyping();
        constraint = data.constraint;
        showConstraintConfirm(constraint);
    } else {
        userMsg("Custom constraint");
        state = "enter_custom_constraint";
        botMsg("Type your constraint:");
        setInputEnabled(true);
        inputEl.placeholder = "e.g. only select left-handed batsmen...";
    }
}

function showConstraintConfirm(c) {
    const div = botMsg(`<b>"${c}"</b>\n\nHappy with this?`);
    const btns = document.createElement("div");
    btns.className = "confirm-buttons";

    const yesBtn = document.createElement("button");
    yesBtn.className = "btn-yes";
    yesBtn.textContent = "Let's go";
    yesBtn.onclick = () => { disableAllButtons(); startDraft(c); };

    const noBtn = document.createElement("button");
    noBtn.textContent = "Reroll";
    noBtn.onclick = async () => {
        disableAllButtons();
        userMsg("Reroll");
        showTyping();
        const resp = await fetch("/api/reroll_constraint", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ format: gameFormat }),
        });
        const data = await resp.json();
        hideTyping();
        constraint = data.constraint;
        showConstraintConfirm(data.constraint);
    };

    btns.appendChild(yesBtn);
    btns.appendChild(noBtn);
    div.appendChild(btns);
}

async function startDraft(c) {
    constraint = c;
    userMsg("Let's go");
    showTyping();

    const resp = await fetch("/api/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            player_names: playerNames,
            num_players: numPlayers,
            format: gameFormat,
            constraint_choice: "custom",
            custom_constraint: constraint,
        }),
    });
    const data = await resp.json();
    hideTyping();

    gameId = data.game_id;
    currentTurnPlayer = data.current_turn;
    pickCount = 0;
    state = "drafting";

    let startMsg = `<b>Draft started!</b> — ${gameFormat}\n\n<b>Constraint:</b> "${constraint}"\n\nPick your 11 players. Type a cricketer's name.\n`;
    if (numPlayers > 1) {
        startMsg += `\n<b>${currentTurnPlayer}</b>, you're up first.\n`;
    }
    startMsg += `<span class="pick-counter">Pick 1 of 11</span>\n\nType <b>hint</b> for a clue · <b>my team</b> to see your squad`;
    botMsg(startMsg);
    setInputEnabled(true);
    inputEl.placeholder = numPlayers > 1 ? `${currentTurnPlayer}'s pick...` : "pick a cricketer...";
}

// --- Draft flow ---

function handlePickSuccess(data) {
    pickCount = data.pick_number;
    currentTurnPlayer = data.current_turn || "";
    const pickedFor = data.picked_for || "";
    const p = data.player;

    let prefix = numPlayers > 1 ? `[${pickedFor}] ` : "";
    botMsg(`${prefix}✅ <b>${p.name}</b> — ${p.country} · ${p.role}` +
        (p.bat_hand !== "?" ? ` · ${p.bat_hand}-hand bat` : "") +
        (p.bowl_style && p.bowl_style !== "N/A" ? ` · ${p.bowl_style}` : ""));
    if (data.stats) statsMsg(data.stats);
    if (data.commentary) commentaryMsg(data.commentary);

    if (data.draft_complete) {
        botMsg("🏆 <b>Draft complete!</b>\n\nType <b>my team</b> to see your final squad.");
        state = "complete";
    } else {
        let turnMsg = `<span class="pick-counter">Pick ${data.next_pick} of 11</span>`;
        if (numPlayers > 1) {
            turnMsg = `<b>${currentTurnPlayer}</b>'s turn — ` + turnMsg;
        }
        addMsg(turnMsg, "msg-bot");
        inputEl.placeholder = numPlayers > 1 ? `${currentTurnPlayer}'s pick...` : "pick a cricketer...";
    }
    setInputEnabled(true);
}

async function handleDraftInput(text) {
    const lower = text.toLowerCase().trim();

    if (lower === "hint") {
        userMsg(text);
        showTyping();
        setInputEnabled(false);
        const resp = await fetch("/api/hint", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ game_id: gameId }),
        });
        const data = await resp.json();
        hideTyping();
        botMsg(`💡 ${data.hint}`);
        setInputEnabled(true);
        return;
    }

    if (lower === "my team" || lower === "team" || lower === "my squad") {
        userMsg(text);
        await showTeam();
        return;
    }

    userMsg(text);
    showTyping();
    setInputEnabled(false);

    const body = { game_id: gameId, cricketer: text };
    if (pendingConfirm) {
        body.confirmed_player = pendingConfirm;
        pendingConfirm = null;
    }

    const resp = await fetch("/api/pick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    hideTyping();

    if (data.status === "picked") {
        handlePickSuccess(data);

    } else if (data.status === "confirm") {
        const div = botMsg(data.message);
        const btns = document.createElement("div");
        btns.className = "confirm-buttons";

        const yesBtn = document.createElement("button");
        yesBtn.className = "btn-yes";
        yesBtn.textContent = "Yes";
        yesBtn.onclick = () => {
            disableAllButtons();
            userMsg("Yes");
            pendingConfirm = data.candidate;
            showTyping();
            setInputEnabled(false);
            confirmPick(text, data.candidate);
        };

        const noBtn = document.createElement("button");
        noBtn.textContent = "No";
        noBtn.onclick = () => {
            disableAllButtons();
            userMsg("No");
            botMsg("No worries — try another name.");
            setInputEnabled(true);
            inputEl.focus();
        };

        btns.appendChild(yesBtn);
        btns.appendChild(noBtn);
        div.appendChild(btns);

    } else if (data.status === "choose") {
        const div = botMsg(data.message);
        const list = document.createElement("div");
        list.className = "candidate-list";
        data.candidates.forEach(c => {
            const btn = document.createElement("button");
            btn.className = "candidate-btn";
            btn.textContent = `${c.name} (${c.country}, ${c.role})`;
            btn.onclick = () => {
                disableAllButtons();
                userMsg(c.name);
                showTyping();
                setInputEnabled(false);
                confirmPick(text, c.name);
            };
            list.appendChild(btn);
        });

        const noneBtn = document.createElement("button");
        noneBtn.className = "candidate-btn";
        noneBtn.textContent = "None of these";
        noneBtn.onclick = () => {
            disableAllButtons();
            userMsg("None of these");
            botMsg("Try a different name.");
            setInputEnabled(true);
            inputEl.focus();
        };
        list.appendChild(noneBtn);

        div.appendChild(list);

    } else if (data.status === "rejected") {
        botMsg(`❌ ${data.message}`);
        setInputEnabled(true);
    }
}

async function confirmPick(originalText, confirmedName) {
    const resp = await fetch("/api/pick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            game_id: gameId,
            cricketer: originalText,
            confirmed_player: confirmedName,
        }),
    });
    const data = await resp.json();
    hideTyping();

    if (data.status === "picked") {
        handlePickSuccess(data);
    } else {
        botMsg(`❌ ${data.message}`);
        setInputEnabled(true);
    }
}

function renderTeamCard(data) {
    const div = document.createElement("div");
    div.className = "msg msg-team";

    const header = document.createElement("div");
    header.className = "team-header";
    header.textContent = `${data.team_name} — ${data.format} (${data.count}/11)`;
    div.appendChild(header);

    const body = document.createElement("div");
    body.className = "team-body";

    let currentRole = null;
    const roleLabels = { "Batsman": "Batsmen", "Wicket-keeper": "Wicket-keepers", "All-rounder": "All-rounders", "Bowler": "Bowlers" };

    data.players.forEach((p, i) => {
        if (p.role !== currentRole) {
            currentRole = p.role;
            const roleRow = document.createElement("div");
            roleRow.className = "team-row role-header";
            roleRow.textContent = roleLabels[currentRole] || currentRole;
            body.appendChild(roleRow);
        }

        const row = document.createElement("div");
        row.className = "team-row";

        const name = document.createElement("span");
        name.className = "player-name";
        name.textContent = `${p.name} (${p.country})`;
        row.appendChild(name);

        const runs = document.createElement("span");
        runs.className = "player-stat";
        runs.textContent = p.runs !== "-" ? `${p.runs}r` : "";
        row.appendChild(runs);

        const avg = document.createElement("span");
        avg.className = "player-stat";
        avg.textContent = p.bat_avg !== "-" && p.bat_avg !== 0 ? `${p.bat_avg}av` : "";
        row.appendChild(avg);

        const wkts = document.createElement("span");
        wkts.className = "player-stat";
        wkts.textContent = p.wickets !== "-" && p.wickets > 0 ? `${p.wickets}w` : "";
        row.appendChild(wkts);

        body.appendChild(row);
    });

    div.appendChild(body);
    messagesEl.appendChild(div);
    scrollToBottom();
}

async function showTeam() {
    showTyping();
    setInputEnabled(false);
    const resp = await fetch("/api/team", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: gameId }),
    });
    const data = await resp.json();
    hideTyping();

    if (data.teams) {
        let anyPicks = false;
        for (const t of data.teams) {
            if (t.count > 0) { anyPicks = true; renderTeamCard(t); }
        }
        if (!anyPicks) botMsg("No picks yet — start drafting!");
    } else {
        if (data.count === 0) {
            botMsg("Your team is empty — start picking!");
        } else {
            renderTeamCard(data);
        }
    }
    setInputEnabled(true);
}

// --- Input handling ---

function handleSend() {
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";

    switch (state) {
        case "ask_name":
            userMsg(text);
            handleName(text);
            break;
        case "enter_custom_constraint":
            userMsg(text);
            constraint = text;
            state = "drafting";
            startDraft(text);
            break;
        case "drafting":
        case "complete":
            handleDraftInput(text);
            break;
    }
}

sendBtn.addEventListener("click", handleSend);
inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSend();
});

// --- Init ---
startSetup();
inputEl.focus();
