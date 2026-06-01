// --------------------------------------------------
// AI DevOps Bot - Main Web Application Logic (SPA)
// --------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
    // Current Active States
    let currentIncidentId = null;
    let incidents = [];
    let kbRules = [];
    
    // API Base URL (Dynamic according to window location)
    const API_BASE = window.location.origin;

    // --- DOM ELEMENTS ---
    // Sidebar Nav
    const navDashboard = document.getElementById("nav-dashboard");
    const navKnowledge = document.getElementById("nav-knowledge");
    const navMetrics = document.getElementById("nav-metrics");
    const views = {
        dashboard: document.getElementById("view-dashboard"),
        knowledge: document.getElementById("view-knowledge"),
        metrics: document.getElementById("view-metrics")
    };

    // Dashboard Elements
    const btnRefreshIncidents = document.getElementById("btn-refresh-incidents");
    const inputIncidentSearch = document.getElementById("incident-search");
    const listIncidents = document.getElementById("incidents-list");
    const loaderIncidents = document.getElementById("incidents-loader");
    const emptyIncidents = document.getElementById("incidents-empty");
    
    // Incident Details
    const detailPlaceholder = document.getElementById("detail-placeholder");
    const detailContent = document.getElementById("detail-content");
    const detailAppBadges = document.getElementById("detail-app-badges");
    const detailTime = document.getElementById("detail-time");
    const btnDeleteIncident = document.getElementById("btn-delete-incident");
    const detailLogsContainer = document.getElementById("detail-logs-container");
    const detailKbrulesCard = document.getElementById("detail-kb-rules-card");
    const detailKbrulesList = document.getElementById("detail-kb-rules-list");
    const detailAiProposal = document.getElementById("detail-ai-proposal");

    // Knowledge Base Elements
    const btnAddRule = document.getElementById("btn-add-rule");
    const inputKbSearch = document.getElementById("kb-search");
    const loaderKb = document.getElementById("kb-loader");
    const emptyKb = document.getElementById("kb-empty");
    const gridKb = document.getElementById("kb-grid");

    // Metrics & Health Elements
    const metricCycles = document.getElementById("metric-cycles");
    const metricErrors = document.getElementById("metric-errors");
    const metricAlerts = document.getElementById("metric-alerts");
    const metricCommands = document.getElementById("metric-commands");
    const healthLokiUrl = document.getElementById("health-loki-url");
    const healthAiProvider = document.getElementById("health-ai-provider");
    const healthPollInterval = document.getElementById("health-poll-interval");

    // Modal Form Elements
    const ruleModal = document.getElementById("rule-modal");
    const btnCloseModal = document.getElementById("btn-close-modal");
    const btnCancelModal = document.getElementById("btn-cancel-modal");
    const ruleForm = document.getElementById("rule-form");
    const modalTitle = document.getElementById("modal-title");
    const fieldOriginalPattern = document.getElementById("field-original-pattern");
    const fieldPattern = document.getElementById("field-pattern");
    const fieldDescription = document.getElementById("field-description");
    const fieldCause = document.getElementById("field-cause");
    const fieldSolution = document.getElementById("field-solution");
    const fieldCommands = document.getElementById("field-commands");

    // Toast Notification
    const toast = document.getElementById("toast-notification");
    const toastMessage = document.getElementById("toast-message");

    // --- NAVIGATION LOGIC ---
    function switchView(targetView) {
        // Toggle Nav Buttons
        navDashboard.classList.toggle("active", targetView === "dashboard");
        navKnowledge.classList.toggle("active", targetView === "knowledge");
        navMetrics.classList.toggle("active", targetView === "metrics");

        // Toggle Content Views
        views.dashboard.classList.toggle("active", targetView === "dashboard");
        views.knowledge.classList.toggle("active", targetView === "knowledge");
        views.metrics.classList.toggle("active", targetView === "metrics");

        // Load View Data
        if (targetView === "dashboard") {
            fetchIncidents();
        } else if (targetView === "knowledge") {
            fetchKbRules();
        } else if (targetView === "metrics") {
            fetchMetricsAndHealth();
        }
    }

    navDashboard.addEventListener("click", () => switchView("dashboard"));
    navKnowledge.addEventListener("click", () => switchView("knowledge"));
    navMetrics.addEventListener("click", () => switchView("metrics"));

    // --- TOAST NOTIFICATIONS ---
    function showToast(message, type = "info") {
        toastMessage.textContent = message;
        toast.className = "toast"; // Reset
        if (type === "error") {
            toast.style.borderLeftColor = "var(--theme-danger)";
        } else if (type === "success") {
            toast.style.borderLeftColor = "var(--theme-success)";
        } else {
            toast.style.borderLeftColor = "var(--accent-primary)";
        }
        
        toast.classList.remove("hide");
        setTimeout(() => {
            toast.classList.add("hide");
        }, 3500);
    }

    // --- UTILITIES ---
    function formatTimestamp(unixTime) {
        const date = new Date(unixTime * 1000);
        return date.toLocaleString("es-ES", {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit"
        });
    }

    // Live sidebar clock
    setInterval(() => {
        const timeStr = new Date().toLocaleTimeString("es-ES");
        document.getElementById("live-time").textContent = timeStr;
    }, 1000);

    // --- INCIDENTS DASHBOARD LOGIC ---
    async function fetchIncidents() {
        loaderIncidents.classList.remove("hide");
        listIncidents.classList.add("hide");
        emptyIncidents.classList.add("hide");

        try {
            const res = await fetch(`${API_BASE}/api/incidents`);
            if (!res.ok) throw new Error("Fallo al consultar incidencias");
            incidents = await res.json();
            renderIncidentsList();
        } catch (err) {
            console.error(err);
            showToast("Error al obtener los incidentes del servidor.", "error");
            emptyIncidents.classList.remove("hide");
        } finally {
            loaderIncidents.classList.add("hide");
        }
    }

    function renderIncidentsList() {
        const query = inputIncidentSearch.value.trim().toLowerCase();
        
        // Filter incidents
        const filtered = incidents.filter(inc => {
            const matchesApp = inc.apps.some(app => app.toLowerCase().includes(query));
            const matchesProposal = inc.ai_proposal.toLowerCase().includes(query);
            return matchesApp || matchesProposal;
        });

        listIncidents.innerHTML = "";
        
        if (filtered.length === 0) {
            emptyIncidents.classList.remove("hide");
            listIncidents.classList.add("hide");
            return;
        }

        emptyIncidents.classList.add("hide");
        listIncidents.classList.remove("hide");

        filtered.forEach(inc => {
            const card = document.createElement("div");
            card.className = `incident-card ${currentIncidentId === inc.id ? "active" : ""}`;
            card.dataset.id = inc.id;

            const appBadges = inc.apps.map(app => `<span class="app-badge">${app}</span>`).join("");
            const kbBadge = inc.matched_rules.length > 0 
                ? `<span class="kb-badge-tag"><i data-lucide="sparkles" style="width:10px;height:10px;"></i> RAG Match</span>` 
                : "";

            card.innerHTML = `
                <div class="card-header-row">
                    <div class="card-apps-badges">${appBadges}</div>
                    <span class="card-time">${formatTimestamp(inc.timestamp).split(" ")[1] || ""}</span>
                </div>
                <p>${inc.ai_proposal.substring(0, 140)}...</p>
                <div class="card-meta-row">
                    <span class="card-time">${formatTimestamp(inc.timestamp).split(" ")[0]}</span>
                    ${kbBadge}
                </div>
            `;

            card.addEventListener("click", () => selectIncident(inc));
            listIncidents.appendChild(card);
        });

        lucide.createIcons();
    }

    function selectIncident(inc) {
        currentIncidentId = inc.id;
        
        // Toggle card visual active state
        document.querySelectorAll(".incident-card").forEach(c => {
            c.classList.toggle("active", parseInt(c.dataset.id) === inc.id);
        });

        // Hide placeholder, show content
        detailPlaceholder.classList.add("hide");
        detailContent.classList.remove("hide");

        // Set Headers
        detailAppBadges.innerHTML = inc.apps.map(app => `<span class="app-badge-large">${app}</span>`).join("");
        detailTime.textContent = formatTimestamp(inc.timestamp);

        // Render Raw Logs
        detailLogsContainer.innerHTML = "";
        
        for (const [app, logsList] of Object.entries(inc.logs)) {
            const appBlock = document.createElement("div");
            appBlock.className = "log-app-block";
            
            const logLines = logsList.map(item => {
                const countText = item.count > 1 ? `<span class="log-item-count">(Ocurrencias: x${item.count})</span>` : "";
                return `<div class="log-item-line"><code>${item.message}</code>${countText}</div>`;
            }).join("");

            appBlock.innerHTML = `
                <div class="log-app-name"><i data-lucide="box" style="width:12px;height:12px;display:inline-block;vertical-align:middle;margin-right:4px;"></i> Contenedor: ${app}</div>
                <div class="log-items-list">${logLines}</div>
            `;
            detailLogsContainer.appendChild(appBlock);
        }

        // Render Matched Knowledge Rules
        if (inc.matched_rules && inc.matched_rules.length > 0) {
            detailKbrulesCard.classList.remove("hide");
            detailKbrulesList.innerHTML = inc.matched_rules.map(rule => `
                <div class="matched-rule-item">
                    <div class="matched-rule-title">💡 Patrón: "${rule.pattern}"</div>
                    <p><strong>Descripción:</strong> ${rule.description || "N/A"}</p>
                    <p><strong>Solución Sugerida:</strong> ${rule.solution}</p>
                </div>
            `).join("");
        } else {
            detailKbrulesCard.classList.add("hide");
        }

        // Render AI proposal with Marked Markdown Parser
        try {
            detailAiProposal.innerHTML = marked.parse(inc.ai_proposal);
            
            // Add custom copy buttons to code blocks inside the AI proposal
            detailAiProposal.querySelectorAll("pre").forEach(preElement => {
                const btnCopy = document.createElement("button");
                btnCopy.className = "btn btn-secondary";
                btnCopy.style.position = "absolute";
                btnCopy.style.top = "8px";
                btnCopy.style.right = "8px";
                btnCopy.style.padding = "4px 8px";
                btnCopy.style.fontSize = "10px";
                btnCopy.innerHTML = '<i data-lucide="copy" style="width:12px;height:12px;"></i> Copiar';
                
                preElement.appendChild(btnCopy);
                
                btnCopy.addEventListener("click", () => {
                    const code = preElement.querySelector("code").textContent;
                    navigator.clipboard.writeText(code);
                    showToast("¡Comando copiado al portapapeles!", "success");
                    btnCopy.innerHTML = '<i data-lucide="check" style="width:12px;height:12px;"></i> Copiado';
                    setTimeout(() => {
                        btnCopy.innerHTML = '<i data-lucide="copy" style="width:12px;height:12px;"></i> Copiar';
                        lucide.createIcons();
                    }, 2000);
                    lucide.createIcons();
                });
            });
        } catch (ex) {
            detailAiProposal.textContent = inc.ai_proposal;
        }

        lucide.createIcons();
    }

    btnRefreshIncidents.addEventListener("click", fetchIncidents);
    inputIncidentSearch.addEventListener("input", renderIncidentsList);

    btnDeleteIncident.addEventListener("click", async () => {
        if (!currentIncidentId) return;
        if (!confirm("¿Estás seguro de que deseas eliminar esta alerta del historial?")) return;

        try {
            const res = await fetch(`${API_BASE}/api/incidents/${currentIncidentId}`, {
                method: "DELETE"
            });
            if (!res.ok) throw new Error("Fallo al eliminar incidente");
            showToast("Incidente eliminado exitosamente.", "success");
            
            currentIncidentId = null;
            detailContent.classList.add("hide");
            detailPlaceholder.classList.remove("hide");
            fetchIncidents();
        } catch (err) {
            console.error(err);
            showToast("Error al intentar eliminar el incidente.", "error");
        }
    });

    // --- KNOWLEDGE BASE (KB) MAP LOGIC ---
    async function fetchKbRules() {
        loaderKb.classList.remove("hide");
        gridKb.classList.add("hide");
        emptyKb.classList.add("hide");

        try {
            const res = await fetch(`${API_BASE}/api/kb`);
            if (!res.ok) throw new Error("Fallo al consultar mapa de conocimiento");
            kbRules = await res.json();
            renderKbGrid();
        } catch (err) {
            console.error(err);
            showToast("Error al cargar el mapa de conocimiento.", "error");
            emptyKb.classList.remove("hide");
        } finally {
            loaderKb.classList.add("hide");
        }
    }

    function renderKbGrid() {
        const query = inputKbSearch.value.trim().toLowerCase();
        
        // Filter rules
        const filtered = kbRules.filter(rule => {
            const matchesPattern = rule.pattern.toLowerCase().includes(query);
            const matchesDesc = (rule.description || "").toLowerCase().includes(query);
            const matchesSolution = (rule.solution || "").toLowerCase().includes(query);
            return matchesPattern || matchesDesc || matchesSolution;
        });

        gridKb.innerHTML = "";
        
        if (filtered.length === 0) {
            emptyKb.classList.remove("hide");
            gridKb.classList.add("hide");
            return;
        }

        emptyKb.classList.add("hide");
        gridKb.classList.remove("hide");

        filtered.forEach(rule => {
            const card = document.createElement("div");
            card.className = "kb-card";

            const descSection = rule.description 
                ? `<div class="kb-card-desc">${rule.description}</div>` 
                : '<div class="kb-card-desc text-muted">Sin descripción.</div>';

            const causeSection = rule.cause 
                ? `<div class="kb-card-field"><span class="label">Causa Probable:</span><span class="value">${rule.cause}</span></div>` 
                : "";

            const commandsSection = rule.commands 
                ? `<div class="kb-card-field code-block"><span class="label">Comando de Autocuración:</span><pre><code>${rule.commands}</code></pre></div>` 
                : "";

            card.innerHTML = `
                <div class="kb-card-header">
                    <span class="kb-card-title">${rule.pattern}</span>
                    <div class="kb-card-actions">
                        <button class="btn-icon btn-edit-rule" title="Editar regla"><i data-lucide="edit-3"></i></button>
                        <button class="btn-icon delete btn-delete-rule" title="Eliminar regla"><i data-lucide="trash-2"></i></button>
                    </div>
                </div>
                ${descSection}
                ${causeSection}
                <div class="kb-card-field">
                    <span class="label">Solución Sugerida:</span>
                    <span class="value">${rule.solution}</span>
                </div>
                ${commandsSection}
            `;

            // Bind Edit event
            card.querySelector(".btn-edit-rule").addEventListener("click", () => openRuleModal(rule));
            
            // Bind Delete event
            card.querySelector(".btn-delete-rule").addEventListener("click", () => deleteKbRule(rule.pattern));

            gridKb.appendChild(card);
        });

        lucide.createIcons();
    }

    inputKbSearch.addEventListener("input", renderKbGrid);

    // Add and Edit Modals
    btnAddRule.addEventListener("click", () => openRuleModal());
    
    function openRuleModal(rule = null) {
        ruleForm.reset();
        
        if (rule) {
            // Edit Mode
            modalTitle.textContent = "Editar Regla de Conocimiento";
            fieldOriginalPattern.value = rule.pattern;
            fieldPattern.value = rule.pattern;
            fieldDescription.value = rule.description || "";
            fieldCause.value = rule.cause || "";
            fieldSolution.value = rule.solution || "";
            fieldCommands.value = rule.commands || "";
        } else {
            // New Mode
            modalTitle.textContent = "Añadir Regla de Conocimiento";
            fieldOriginalPattern.value = "";
        }
        
        ruleModal.classList.remove("hide");
    }

    function closeModal() {
        ruleModal.classList.add("hide");
    }

    btnCloseModal.addEventListener("click", closeModal);
    btnCancelModal.addEventListener("click", closeModal);
    
    ruleForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const payload = {
            original_pattern: fieldOriginalPattern.value.trim(),
            pattern: fieldPattern.value.trim(),
            description: fieldDescription.value.trim(),
            cause: fieldCause.value.trim(),
            solution: fieldSolution.value.trim(),
            commands: fieldCommands.value.trim()
        };

        try {
            const res = await fetch(`${API_BASE}/api/kb`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) throw new Error("Fallo al guardar regla");
            
            showToast("Regla del Mapa de Conocimiento guardada con éxito.", "success");
            closeModal();
            fetchKbRules();
        } catch (err) {
            console.error(err);
            showToast("Error al guardar la regla en el servidor.", "error");
        }
    });

    async function deleteKbRule(pattern) {
        if (!confirm(`¿Estás seguro de que deseas eliminar la regla para el patrón "${pattern}"?`)) return;

        try {
            const res = await fetch(`${API_BASE}/api/kb?pattern=${encodeURIComponent(pattern)}`, {
                method: "DELETE"
            });

            if (!res.ok) throw new Error("Fallo al eliminar regla");
            showToast("Regla eliminada exitosamente.", "success");
            fetchKbRules();
        } catch (err) {
            console.error(err);
            showToast("Error al intentar eliminar la regla.", "error");
        }
    }

    // --- METRICS & HEALTH INFORMATION ---
    async function fetchMetricsAndHealth() {
        // Fetch health endpoints
        try {
            const resMetrics = await fetch(`${API_BASE}/metrics`);
            if (resMetrics.ok) {
                const text = await resMetrics.text();
                parsePrometheusMetrics(text);
            }
            
            // Render basic system operational details
            healthLokiUrl.textContent = "Acceso Local / Grafana Loki Agent";
            healthAiProvider.textContent = "Google Gemini Pro / Groq Cloud";
            healthPollInterval.textContent = "Cada 60 segundos (Seguro)";
        } catch (err) {
            console.error("Error al consultar telemetría:", err);
            showToast("No se pudo conectar con el servidor de métricas del bot.", "error");
        }
    }

    function parsePrometheusMetrics(metricsText) {
        const lines = metricsText.split("\n");
        lines.forEach(line => {
            if (line.startsWith("#") || !line.trim()) return;
            const parts = line.split(" ");
            if (parts.length < 2) return;
            
            const metricName = parts[0];
            const metricVal = parseInt(parts[1]);

            if (metricName === "ai_devops_bot_cycles_total") {
                metricCycles.textContent = metricVal;
            } else if (metricName === "ai_devops_bot_errors_detected_total") {
                metricErrors.textContent = metricVal;
            } else if (metricName === "ai_devops_bot_alerts_sent_total") {
                metricAlerts.textContent = metricVal;
            } else if (metricName === "ai_devops_bot_commands_executed_total") {
                metricCommands.textContent = metricVal;
            }
        });
    }

    // --- INITIALIZE SPA ---
    switchView("dashboard");
});
