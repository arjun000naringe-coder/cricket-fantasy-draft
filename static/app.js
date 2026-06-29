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
let currentTurnIndex = 0;

let typeQueue = Promise.resolve();

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

function scrollToElement(el) {
    const chat = document.getElementById("chat");
    requestAnimationFrame(() => { el.scrollIntoView({ behavior: "smooth", block: "start" }); });
}

function typeText(div, html, speed) {
    return new Promise(resolve => {
        let chars = [];
        let i = 0;
        while (i < html.length) {
            if (html[i] === '<') {
                let end = html.indexOf('>', i);
                if (end !== -1) {
                    chars.push(html.substring(i, end + 1));
                    i = end + 1;
                    continue;
                }
            }
            if (html[i] === '&') {
                let end = html.indexOf(';', i);
                if (end !== -1 && end - i < 10) {
                    chars.push(html.substring(i, end + 1));
                    i = end + 1;
                    continue;
                }
            }
            chars.push(html[i]);
            i++;
        }

        div.innerHTML = '';
        div.classList.add('cursor-blink');
        let pos = 0;
        let buf = '';

        function tick() {
            if (pos >= chars.length) {
                div.classList.remove('cursor-blink');
                resolve();
                return;
            }
            let chunk = chars[pos];
            buf += chunk;
            div.innerHTML = buf;
            pos++;
            if (chunk.startsWith('<') || chunk.startsWith('&')) {
                tick();
            } else {
                scrollToBottom();
                setTimeout(tick, speed);
            }
        }
        tick();
    });
}

function queueTyped(text, cls, speed = 18) {
    let div;
    typeQueue = typeQueue.then(() => {
        div = document.createElement("div");
        div.className = `msg ${cls}`;
        messagesEl.appendChild(div);
        scrollToBottom();
        return typeText(div, text, speed);
    });
    return typeQueue;
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

function getPlayerIndex(name) {
    const idx = playerNames.indexOf(name);
    return idx >= 0 ? idx : 0;
}

function showTurnBanner(playerName, pickNum) {
    const idx = getPlayerIndex(playerName);
    const div = document.createElement("div");
    div.className = `turn-banner player-${idx}`;
    div.textContent = `${playerName}'s turn — Pick ${pickNum} of 11`;
    messagesEl.appendChild(div);
    scrollToBottom();
}

function botMsg(text) { return addMsg(text, "msg-bot"); }
function botMsgTyped(text) { return queueTyped(text, "msg-bot", 8); }
function userMsg(text, playerIdx) {
    const cls = playerIdx !== undefined ? `msg-user player-${playerIdx}` : "msg-user";
    addMsg(text, cls);
}
function statsMsg(html) {
    const div = document.createElement("div");
    div.className = "msg msg-stats";
    div.innerHTML = html;
    messagesEl.appendChild(div);
    scrollToBottom();
}
function commentaryMsg(text) {
    const div = document.createElement("div");
    div.className = "msg-commentary";
    div.textContent = text;
    messagesEl.appendChild(div);
    scrollToBottom();
}

// --- Setup flow ---

function startSetup() {
    const div = botMsg("Cricket Fantasy Draft v1.0\n\nBuild your dream XI under a constraint — every pick counts.\n\nHow many players?");
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
        b.style.opacity = "0.4";
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
    currentTurnIndex = getPlayerIndex(currentTurnPlayer);
    pickCount = 0;
    state = "drafting";

    let startMsg = `<b>Draft started!</b> — ${gameFormat}\n\n<b>Constraint:</b> "${constraint}"\n\nPick your 11 players. Type a cricketer's name.\n`;
    startMsg += `\nType <b>hint</b> for a clue · <b>my team</b> to see your squad`;
    botMsg(startMsg);
    if (numPlayers > 1) {
        showTurnBanner(currentTurnPlayer, 1);
    } else {
        addMsg(`<span class="pick-counter">Pick 1 of 11</span>`, "msg-bot");
    }
    setInputEnabled(true);
    inputEl.placeholder = numPlayers > 1 ? `${currentTurnPlayer}'s pick...` : "pick a cricketer...";
}

// --- Draft flow ---

async function handlePickSuccess(data) {
    pickCount = data.pick_number;
    currentTurnPlayer = data.current_turn || "";
    currentTurnIndex = getPlayerIndex(currentTurnPlayer);
    const p = data.player;

    if (data.stats) statsMsg(data.stats);
    if (data.commentary) commentaryMsg(data.commentary);

    if (data.draft_complete) {
        await botMsgTyped("Draft complete!");
        state = "complete";
        showPostDraftOptions();
    } else {
        if (numPlayers > 1) {
            showTurnBanner(currentTurnPlayer, data.next_pick);
        } else {
            addMsg(`<span class="pick-counter">Pick ${data.next_pick} of 11</span>`, "msg-bot");
        }
        inputEl.placeholder = numPlayers > 1 ? `${currentTurnPlayer}'s pick...` : "pick a cricketer...";
    }
    setInputEnabled(true);
}

async function handleDraftInput(text) {
    const lower = text.toLowerCase().trim();

    if ((lower === "simulate" || lower === "simulate match") && state === "complete" && numPlayers >= 2) {
        userMsg(text);
        showSimulationSetup();
        return;
    }

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
        await botMsgTyped(data.hint);
        setInputEnabled(true);
        return;
    }

    if (lower === "my team" || lower === "team" || lower === "my squad") {
        userMsg(text);
        await showTeam();
        return;
    }

    if (pickCount > 0) {
        const sep = document.createElement("div");
        sep.className = "pick-separator";
        messagesEl.appendChild(sep);
    }
    userMsg(text, numPlayers > 1 ? currentTurnIndex : undefined);
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
            userMsg("Yes", numPlayers > 1 ? currentTurnIndex : undefined);
            showTyping();
            setInputEnabled(false);
            confirmPick(text, data.candidate);
        };

        const noBtn = document.createElement("button");
        noBtn.textContent = "No, search ESPN";
        noBtn.onclick = async () => {
            disableAllButtons();
            userMsg("No", numPlayers > 1 ? currentTurnIndex : undefined);
            showTyping();
            setInputEnabled(false);
            const resp2 = await fetch("/api/pick", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ game_id: gameId, cricketer: text, force_espn: true }),
            });
            const data2 = await resp2.json();
            hideTyping();
            if (data2.status === "confirm") {
                const div2 = botMsg(data2.message);
                const btns2 = document.createElement("div");
                btns2.className = "confirm-buttons";
                const yesBtn2 = document.createElement("button");
                yesBtn2.className = "btn-yes";
                yesBtn2.textContent = "Yes";
                yesBtn2.onclick = () => {
                    disableAllButtons();
                    userMsg("Yes", numPlayers > 1 ? currentTurnIndex : undefined);
                    showTyping();
                    setInputEnabled(false);
                    confirmPick(text, data2.candidate);
                };
                const noBtn2 = document.createElement("button");
                noBtn2.textContent = "No";
                noBtn2.onclick = () => {
                    disableAllButtons();
                    userMsg("No", numPlayers > 1 ? currentTurnIndex : undefined);
                    botMsg("No worries — try another name.");
                    setInputEnabled(true);
                    inputEl.focus();
                };
                btns2.appendChild(yesBtn2);
                btns2.appendChild(noBtn2);
                div2.appendChild(btns2);
            } else if (data2.status === "picked") {
                handlePickSuccess(data2);
            } else {
                botMsg(data2.message || "Could not find that player online either. Try another name.");
                setInputEnabled(true);
                inputEl.focus();
            }
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
            btn.innerHTML = `<span class="cand-name">${c.name}</span> <span class="cand-info">— ${c.country}, ${c.role}</span>`;
            btn.onclick = () => {
                disableAllButtons();
                userMsg(c.name, numPlayers > 1 ? currentTurnIndex : undefined);
                showTyping();
                setInputEnabled(false);
                confirmPick(text, c.name);
            };
            list.appendChild(btn);
        });

        const noneBtn = document.createElement("button");
        noneBtn.className = "candidate-btn";
        noneBtn.textContent = "None of these — search online";
        noneBtn.onclick = async () => {
            disableAllButtons();
            userMsg("None of these", numPlayers > 1 ? currentTurnIndex : undefined);
            showTyping();
            setInputEnabled(false);
            const resp2 = await fetch("/api/pick", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ game_id: gameId, cricketer: text, force_espn: true }),
            });
            const data2 = await resp2.json();
            hideTyping();
            if (data2.status === "picked") {
                handlePickSuccess(data2);
            } else if (data2.status === "confirm") {
                const div2 = botMsg(data2.message);
                const btns2 = document.createElement("div");
                btns2.className = "confirm-buttons";
                const yesBtn2 = document.createElement("button");
                yesBtn2.className = "btn-yes";
                yesBtn2.textContent = "Yes";
                yesBtn2.onclick = () => {
                    disableAllButtons();
                    userMsg("Yes", numPlayers > 1 ? currentTurnIndex : undefined);
                    showTyping();
                    setInputEnabled(false);
                    confirmPick(text, data2.candidate);
                };
                const noBtn2 = document.createElement("button");
                noBtn2.textContent = "No";
                noBtn2.onclick = () => {
                    disableAllButtons();
                    userMsg("No", numPlayers > 1 ? currentTurnIndex : undefined);
                    botMsg("No worries — try another name.");
                    setInputEnabled(true);
                };
                btns2.appendChild(yesBtn2);
                btns2.appendChild(noBtn2);
                div2.appendChild(btns2);
            } else {
                await botMsgTyped(data2.message || "Could not find this player.");
                setInputEnabled(true);
            }
        };
        list.appendChild(noneBtn);

        div.appendChild(list);

    } else if (data.status === "rejected") {
        const rejDiv = document.createElement("div");
        rejDiv.className = "msg-rejected";
        rejDiv.innerHTML = `<span class="badge badge-rejected">REJECTED</span> ${data.message}`;
        messagesEl.appendChild(rejDiv);
        scrollToBottom();
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
        await handlePickSuccess(data);
    } else {
        const rejDiv = document.createElement("div");
        rejDiv.className = "msg-rejected";
        rejDiv.innerHTML = `<span class="badge badge-rejected">REJECTED</span> ${data.message}`;
        messagesEl.appendChild(rejDiv);
        scrollToBottom();
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

    const colHeader = document.createElement("div");
    colHeader.className = "team-row team-col-header";
    colHeader.innerHTML = `<span class="player-name"></span><span class="player-stat">Runs</span><span class="player-stat">Avg</span><span class="player-stat">Wkts</span><span class="player-stat">Avg</span>`;
    body.appendChild(colHeader);

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
        runs.textContent = p.runs !== "-" ? `${p.runs}` : "";
        row.appendChild(runs);

        const avg = document.createElement("span");
        avg.className = "player-stat";
        avg.textContent = p.bat_avg !== "-" && p.bat_avg !== 0 ? `${p.bat_avg}` : "";
        row.appendChild(avg);

        const wkts = document.createElement("span");
        wkts.className = "player-stat";
        wkts.textContent = p.wickets !== "-" && p.wickets > 0 ? `${p.wickets}` : "";
        row.appendChild(wkts);

        const bowlAvg = document.createElement("span");
        bowlAvg.className = "player-stat";
        bowlAvg.textContent = p.bowl_avg !== "-" && p.bowl_avg > 0 ? `${p.bowl_avg}` : "";
        row.appendChild(bowlAvg);

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
    if (state === "drafting") {
        if (numPlayers > 1) {
            showTurnBanner(currentTurnPlayer, data.next_pick || "?");
        } else {
            addMsg(`<span class="pick-counter">Pick ${data.next_pick || "?"} of 11</span>`, "msg-bot");
        }
    }
    setInputEnabled(true);
}

// --- Match simulation ---

let simNumMatches = 1;
let simVenueCountry = "";

function showSimulationSetup() {
    const div = botMsg("How many matches in the series?");
    const opts = document.createElement("div");
    opts.className = "setup-options";
    [1, 3, 5].forEach(n => {
        const btn = document.createElement("button");
        btn.textContent = n === 1 ? "1 match" : `${n}-match series`;
        btn.onclick = () => {
            disableAllButtons();
            userMsg(btn.textContent);
            simNumMatches = n;
            askVenueCountry();
        };
        opts.appendChild(btn);
    });
    div.appendChild(opts);
}

async function askVenueCountry() {
    showTyping();
    const resp = await fetch("/api/venues");
    const data = await resp.json();
    hideTyping();

    const div = botMsg("Where should the series be played?");
    const opts = document.createElement("div");
    opts.className = "setup-options";

    const wwBtn = document.createElement("button");
    wwBtn.textContent = "Worldwide (random venues)";
    wwBtn.onclick = () => { disableAllButtons(); selectVenue("Worldwide"); };
    opts.appendChild(wwBtn);

    data.countries.forEach(country => {
        const btn = document.createElement("button");
        btn.textContent = country;
        btn.onclick = () => { disableAllButtons(); selectVenue(country); };
        opts.appendChild(btn);
    });
    div.appendChild(opts);
}

function selectVenue(country) {
    simVenueCountry = country;
    userMsg(country);
    state = "simulating";
    simulateMatch();
}

function renderBattingTable(inn, label) {
    const top = inn.batting.filter(b => b.runs > 0 || !b.out).slice(0, 4);
    if (!top.length) return "";
    let rows = top.map(b => {
        const notOut = !b.out ? "*" : "";
        return `<tr><td>${b.name}</td><td class="highlight">${b.runs}${notOut}</td><td>${b.balls}</td><td>${b.balls > 0 ? Math.round(b.runs / b.balls * 100) : 0}</td></tr>`;
    }).join("");
    return `<div class="sim-stats-card"><div class="card-header"><span class="card-label">${label} — ${inn.batting_team}</span><span class="card-score">${inn.total}/${inn.wickets}</span></div><table><tr><th>Player</th><th>R</th><th>B</th><th>SR</th></tr>${rows}</table></div>`;
}

function renderBowlingTable(inn, label) {
    const top = inn.bowling.filter(b => b.wickets > 0).slice(0, 3);
    if (!top.length) return "";
    let rows = top.map(b => {
        return `<tr><td>${b.name}</td><td class="highlight">${b.wickets}</td><td>${b.runs}</td><td>${b.overs}</td></tr>`;
    }).join("");
    return `<div class="sim-stats-card"><div class="card-header"><span class="card-label">${label} — ${inn.bowling_team}</span></div><table><tr><th>Player</th><th>W</th><th>R</th><th>Ov</th></tr>${rows}</table></div>`;
}

function renderMatchResult(match) {
    const r = match.winner
        ? `${match.winner} won by ${match.margin}`
        : match.result_line;
    let potmHtml = "";
    if (match.potm) {
        potmHtml = `<div class="potm"><div class="potm-label">Player of the match</div><div class="potm-name">${match.potm.name} — ${match.potm.reason}</div></div>`;
    }
    return `<div class="match-result"><div class="result-label">Result</div><div class="result-text">${r}</div>${potmHtml}</div>`;
}

function renderMatchSituation(innings, matchFormat) {
    if (innings.length < 2) return "";
    const inn1 = innings[0];
    const inn2 = innings[1];

    if (matchFormat === "Test") {
        if (innings.length >= 4) {
            const inn4 = innings[3];
            const target = innings[2] ? inn1.total - innings[2].total + innings[2].total + 1 : inn1.total + 1;
            return "";
        }
        return "";
    }

    const target = inn1.total + 1;
    const remaining = target - inn2.total;
    const wicketsLeft = 10 - inn2.wickets;
    if (remaining > 0 && wicketsLeft > 0) {
        return `<div class="match-situation"><div class="situation-label">Match situation</div><div class="situation-text">${inn2.batting_team} needed <span class="num">${remaining} runs</span> from <span class="num">${wicketsLeft} wickets</span></div></div>`;
    }
    return "";
}

async function simulateMatch() {
    const loadMsg = botMsg(`Simulating ${simNumMatches > 1 ? simNumMatches + "-match series" : "match"} in ${simVenueCountry}...\n\n<span class="pick-counter">This may take a minute${simNumMatches > 1 ? " or two" : ""}${gameFormat === "Test" ? " — Test matches are simulated day by day" : ""}.</span>`);
    showTyping();
    setInputEnabled(false);

    const resp = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: gameId, num_matches: simNumMatches, venue_country: simVenueCountry }),
    });
    const data = await resp.json();
    hideTyping();
    state = "complete";

    if (data.error) {
        botMsg(data.error);
        setInputEnabled(true);
        return;
    }

    let firstMatchEl = null;

    for (const series of data.results) {
        const teamA = series.team_a;
        const teamB = series.team_b;

        for (let mi = 0; mi < series.matches.length; mi++) {
            const match = series.matches[mi];
            const matchTitle = match.match_number ? `Match ${match.match_number}` : "Match";
            const venueStr = match.venue || "";

            // Match header with pitch conditions
            const headerDiv = document.createElement("div");
            headerDiv.className = "match-header";
            let pitchHtml = "";
            if (match.pitch_desc) {
                const desc = match.pitch_desc;
                const highlighted = desc.replace(/(spinners?|pacers?|seamers?|swing|bounce|turn|fast bowlers?)/gi, '<span class="pitch-highlight">$1</span>');
                pitchHtml = `<div class="pitch-info"><span class="badge badge-pitch">PITCH</span> <span>${highlighted}</span></div>`;
            }
            headerDiv.innerHTML = `<div class="match-header-title"><span class="match-name">${teamA}'s XI vs ${teamB}'s XI — ${matchTitle}</span><span class="match-format">${match.format || gameFormat}</span></div><div class="match-venue">${venueStr}</div>${pitchHtml}`;
            messagesEl.appendChild(headerDiv);

            if (!firstMatchEl) firstMatchEl = headerDiv;

            // Toss
            if (match.toss) {
                addMsg(match.toss, "msg-bot");
            }

            // Render innings as structured tables with narratives
            const innings = match.innings || [];
            const segments = match.segments || [];

            if (match.format === "Test" || (match.format || gameFormat) === "Test") {
                // Test: render day-by-day with scorecard tables + situation
                for (let si = 0; si < segments.length; si++) {
                    const seg = segments[si];
                    const segDiv = document.createElement("div");
                    segDiv.className = "msg-sim-segment";

                    let segHtml = `<div class="sim-segment-label">${seg.label}</div>`;
                    if (seg.narrative) {
                        segHtml += `<div class="sim-narrative">${seg.narrative}</div>`;
                    }
                    segDiv.innerHTML = segHtml;
                    messagesEl.appendChild(segDiv);

                    if (seg.snapshot) {
                        const snap = seg.snapshot;

                        // Stumps score line
                        const stumpsDiv = document.createElement("div");
                        stumpsDiv.className = "day-snapshot";
                        let stumpsHtml = '<div class="stumps-scores">';
                        snap.stumps.forEach(s => {
                            stumpsHtml += `<div class="stumps-line">${s}</div>`;
                        });
                        stumpsHtml += '</div>';
                        if (snap.situation) {
                            stumpsHtml += `<div class="day-situation">${snap.situation}</div>`;
                        }
                        stumpsDiv.innerHTML = stumpsHtml;
                        messagesEl.appendChild(stumpsDiv);

                        // Full scorecard tables for innings completed this day
                        if (snap.show_innings && snap.show_innings.length > 0) {
                            for (const ii of snap.show_innings) {
                                if (ii < innings.length) {
                                    const inn = innings[ii];
                                    const tableDiv = document.createElement("div");
                                    tableDiv.innerHTML = renderBattingTable(inn, `Innings ${ii + 1}`) + renderBowlingTable(inn, `Bowling`);
                                    messagesEl.appendChild(tableDiv);
                                }
                            }
                        }
                    }
                }
            } else {
                // Limited overs: render each innings with tables
                for (let ii = 0; ii < innings.length; ii++) {
                    const inn = innings[ii];
                    const seg = segments[ii] || {};
                    const label = ii === 0 ? "First innings" : "Second innings";

                    const segDiv = document.createElement("div");
                    segDiv.className = "msg-sim-segment";
                    segDiv.innerHTML = `<div class="sim-segment-label">${label}</div>`;
                    messagesEl.appendChild(segDiv);

                    const tableDiv = document.createElement("div");
                    tableDiv.innerHTML = renderBattingTable(inn, "Batting") + renderBowlingTable(inn, "Bowling");
                    messagesEl.appendChild(tableDiv);

                    if (seg.narrative) {
                        const narDiv = document.createElement("div");
                        narDiv.className = "sim-narrative";
                        narDiv.textContent = seg.narrative;
                        messagesEl.appendChild(narDiv);
                    }
                }
            }

            // Result
            const resultDiv = document.createElement("div");
            resultDiv.innerHTML = renderMatchResult(match);
            messagesEl.appendChild(resultDiv);
        }

        if (series.series_summary) {
            const sumDiv = document.createElement("div");
            sumDiv.className = "msg msg-sim-summary";
            sumDiv.innerHTML = series.series_summary;
            messagesEl.appendChild(sumDiv);
        }
    }

    // Scroll to start of simulation, not bottom
    if (firstMatchEl) {
        scrollToElement(firstMatchEl);
    }

    showPostSimOptions();
}

function showPostDraftOptions() {
    const div = botMsg("What next?");
    const opts = document.createElement("div");
    opts.className = "setup-options";

    if (numPlayers >= 2) {
        const simBtn = document.createElement("button");
        simBtn.textContent = "Simulate match";
        simBtn.onclick = () => {
            disableAllButtons();
            userMsg("Simulate match");
            showSimulationSetup();
        };
        opts.appendChild(simBtn);
    }

    const teamBtn = document.createElement("button");
    teamBtn.textContent = "My team";
    teamBtn.onclick = () => {
        disableAllButtons();
        userMsg("My team");
        showTeam().then(() => showPostDraftOptions());
    };
    opts.appendChild(teamBtn);

    const newBtn = document.createElement("button");
    newBtn.textContent = "Start new game";
    newBtn.onclick = () => {
        disableAllButtons();
        userMsg("Start new game");
        resetGame();
    };
    opts.appendChild(newBtn);

    div.appendChild(opts);
}

function showPostSimOptions() {
    const div = botMsg("What next?");
    const opts = document.createElement("div");
    opts.className = "setup-options";

    const simBtn = document.createElement("button");
    simBtn.textContent = "Simulate again";
    simBtn.onclick = () => {
        disableAllButtons();
        userMsg("Simulate again");
        showSimulationSetup();
    };
    opts.appendChild(simBtn);

    const teamBtn = document.createElement("button");
    teamBtn.textContent = "My team";
    teamBtn.onclick = () => {
        disableAllButtons();
        userMsg("My team");
        showTeam().then(() => showPostSimOptions());
    };
    opts.appendChild(teamBtn);

    const newBtn = document.createElement("button");
    newBtn.textContent = "Start new game";
    newBtn.onclick = () => {
        disableAllButtons();
        userMsg("Start new game");
        resetGame();
    };
    opts.appendChild(newBtn);

    div.appendChild(opts);
    setInputEnabled(true);
}

function resetGame() {
    gameId = null;
    numPlayers = 1;
    playerNames = [];
    currentNamingIndex = 0;
    gameFormat = "";
    constraint = "";
    pickCount = 0;
    pendingConfirm = null;
    currentTurnPlayer = "";
    currentTurnIndex = 0;
    simNumMatches = 1;
    simVenueCountry = "";
    messagesEl.innerHTML = "";
    state = "ask_num_players";
    startSetup();
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
        case "ask_venue":
            userMsg(text);
            selectVenue(text);
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
