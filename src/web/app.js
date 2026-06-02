// --------------------------------------------------
// AI DevOps Bot - Main Web Application Logic (SPA) - Phase 2
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
    const detailIncidentNum = document.getElementById("detail-incident-num");
    const detailStatusBadge = document.getElementById("detail-status-badge");
    const detailAppBadges = document.getElementById("detail-app-badges");
    const detailTime = document.getElementById("detail-time");
    const btnResolveIncident = document.getElementById("btn-resolve-incident");
    const btnDeleteIncident = document.getElementById("btn-delete-incident");
    const detailLogsContainer = document.getElementById("detail-logs-container");
    const detailKbrulesCard = document.getElementById("detail-kb-rules-card");
    const detailKbrulesList = document.getElementById("detail-kb-rules-list");
    const detailHistoryCard = document.getElementById("detail-history-card");
    const detailHistoryTimeline = document.getElementById("detail-history-timeline");
    const detailAppliedKbCard = document.getElementById("detail-applied-kb-card");
    const detailAppliedKbTitle = document.getElementById("detail-applied-kb-title");
    const detailAppliedKbDesc = document.getElementById("detail-applied-kb-desc");
    const detailAppliedKbSol = document.getElementById("detail-applied-kb-sol");
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

    // Rule Modal Elements (Add & Edit)
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

    // Resolve Incident Modal Elements
    const resolveModal = document.getElementById("resolve-modal");
    const btnCloseResolveModal = document.getElementById("btn-close-resolve-modal");
    const btnCancelResolveModal = document.getElementById("btn-cancel-resolve-modal");
    const resolveForm = document.getElementById("resolve-form");
    const fieldResolveIncidentId = document.getElementById("field-resolve-incident-id");
    const fieldResolveKbRule = document.getElementById("field-resolve-kb-rule");
    const btnResolveCreateRule = document.getElementById("btn-resolve-create-rule");

    // Toast Notification
    const toast = document.getElementById("toast-notification");
    const toastMessage = document.getElementById("toast-message");

    // Flag to handle rule creation directly from resolution modal
    let isCreatingRuleFromResolve = false;

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
            
            // Re-select current active incident to load fresh details if still present
            if (currentIncidentId) {
                const currentInc = incidents.find(inc => inc.id === currentIncidentId);
                if (currentInc) {
                    selectIncident(currentInc);
                } else {
                    currentIncidentId = null;
                    detailContent.classList.add("hide");
                    detailPlaceholder.classList.remove("hide");
                }
            }
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
            const matchesNum = inc.incident_num.toLowerCase().includes(query);
            const matchesProposal = inc.ai_proposal.toLowerCase().includes(query);
            const matchesStatus = inc.status.toLowerCase().includes(query);
            return matchesApp || matchesNum || matchesProposal || matchesStatus;
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
            
            // Status Tag styling
            let statusClass = "status-open";
            if (inc.status === "RESUELTA") statusClass = "status-resolved";
            if (inc.status === "CERRADA") statusClass = "status-closed";
            
            const statusBadge = `<span class="status-badge ${statusClass}" style="font-size:8px; padding: 1px 6px;">${inc.status}</span>`;
            
            const kbBadge = inc.matched_rules.length > 0 
                ? `<span class="kb-badge-tag"><i data-lucide="sparkles" style="width:10px;height:10px;"></i> RAG Match</span>` 
                : "";
                
            const reopenBadge = inc.history.length > 0
                ? `<span class="kb-badge-tag" style="background-color: rgba(239,68,68,0.06); color:var(--theme-danger); border-color: rgba(239,68,68,0.15);"><i data-lucide="history" style="width:10px;height:10px;"></i> R-${inc.history.length}</span>`
                : "";

            card.innerHTML = `
                <div class="card-header-row">
                    <div style="display:flex; flex-direction:column; gap:4px;">
                        <span style="font-family:var(--font-mono); font-size:11px; font-weight:800; color:var(--text-muted);">${inc.incident_num}</span>
                        <div class="card-apps-badges">${appBadges}</div>
                    </div>
                    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
                        <span class="card-time">${formatTimestamp(inc.created_at).split(" ")[1] || ""}</span>
                        ${statusBadge}
                    </div>
                </div>
                <p style="margin-top:6px;">${inc.ai_proposal.substring(0, 120)}...</p>
                <div class="card-meta-row">
                    <span class="card-time">${formatTimestamp(inc.created_at).split(" ")[0]}</span>
                    ${kbBadge}
                    ${reopenBadge}
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
        detailIncidentNum.textContent = inc.incident_num;
        detailStatusBadge.textContent = inc.status;
        detailStatusBadge.className = `status-badge ${inc.status === "RESUELTA" ? "status-resolved" : (inc.status === "CERRADA" ? "status-closed" : "status-open")}`;
        detailAppBadges.innerHTML = inc.apps.map(app => `<span class="app-badge-large">${app}</span>`).join("");
        detailTime.textContent = formatTimestamp(inc.created_at);

        // Hide or Show "Resolve" Button based on status
        if (inc.status === "ABIERTA") {
            btnResolveIncident.classList.remove("hide");
        } else {
            btnResolveIncident.classList.add("hide");
        }

        // Render Applied Solution if Resolved
        if (inc.status === "RESUELTA" && inc.kb_applied) {
            detailAppliedKbCard.classList.remove("hide");
            detailAppliedKbTitle.innerHTML = `<i data-lucide="check-check" style="width:14px; height:14px; display:inline-block; vertical-align:middle; margin-right:4px;"></i> Solución: "${inc.kb_applied.pattern}"`;
            detailAppliedKbDesc.innerHTML = `<strong>Diagnóstico del Admin:</strong> ${inc.kb_applied.cause || "N/A"}`;
            detailAppliedKbSol.innerHTML = `<strong>Acción Ejecutada:</strong> ${inc.kb_applied.solution}`;
        } else {
            detailAppliedKbCard.classList.add("hide");
        }

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

        // Render Matched Knowledge Rules in Detection
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

        // Render Recurrence / Reopening Timeline History
        if (inc.history && inc.history.length > 0) {
            detailHistoryCard.classList.remove("hide");
            
            // Build timeline items
            let timelineHtml = `
                <div class="timeline-item create">
                    <div class="timeline-time">${formatTimestamp(inc.created_at)}</div>
                    <div class="timeline-title">Primer Registro del Incidente</div>
                </div>
            `;
            
            inc.history.forEach((h, index) => {
                timelineHtml += `
                    <div class="timeline-item reopen">
                        <div class="timeline-time">${formatTimestamp(h.timestamp)}</div>
                        <div class="timeline-title">Recurrencia del Error #${index + 1}</div>
                        <div class="timeline-desc">${h.message} <span class="log-item-count">(Ocurrencias en ciclo: x${h.count})</span></div>
                    </div>
                `;
            });
            detailHistoryTimeline.innerHTML = timelineHtml;
        } else {
            detailHistoryCard.classList.add("hide");
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

    // --- RESOLVE INCIDENT MODAL LOGIC ---
    btnResolveIncident.addEventListener("click", () => {
        if (!currentIncidentId) return;
        openResolveModal(currentIncidentId);
    });

    async function openResolveModal(incidentId) {
        fieldResolveIncidentId.value = incidentId;
        
        // Fetch fresh KB rules to populate the select dropdown
        await fetchKbRulesForResolveDropdown();
        
        resolveModal.classList.remove("hide");
    }

    async function fetchKbRulesForResolveDropdown() {
        try {
            const res = await fetch(`${API_BASE}/api/kb`);
            if (!res.ok) throw new Error("Fallo al cargar base de conocimientos");
            kbRules = await res.json();
            
            fieldResolveKbRule.innerHTML = "";
            
            if (kbRules.length === 0) {
                const opt = document.createElement("option");
                opt.value = "";
                opt.textContent = "-- No hay reglas. ¡Crea una nueva! --";
                fieldResolveKbRule.appendChild(opt);
                return;
            }
            
            kbRules.forEach(rule => {
                const opt = document.createElement("option");
                opt.value = rule.pattern;
                opt.textContent = `${rule.pattern} (${rule.description || "Sin descripción"})`;
                fieldResolveKbRule.appendChild(opt);
            });
        } catch (err) {
            console.error(err);
            showToast("Error al cargar reglas del mapa de conocimientos para resolución.", "error");
        }
    }

    function closeResolveModal() {
        resolveModal.classList.add("hide");
        isCreatingRuleFromResolve = false;
    }

    btnCloseResolveModal.addEventListener("click", closeResolveModal);
    btnCancelResolveModal.addEventListener("click", closeResolveModal);

    // Resolve Submission
    resolveForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const incidentId = fieldResolveIncidentId.value;
        const selectedPattern = fieldResolveKbRule.value;
        
        if (!selectedPattern) {
            showToast("Por favor, selecciona una regla del Mapa de Conocimientos para resolver el incidente.", "error");
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/incidents/${incidentId}/resolve`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ kb_pattern: selectedPattern })
            });

            if (!res.ok) throw new Error("Fallo al resolver incidente");
            
            showToast(`Incidente marcado como RESUELTO aplicando regla: "${selectedPattern}"`, "success");
            closeResolveModal();
            fetchIncidents();
        } catch (err) {
            console.error(err);
            showToast("Error al intentar resolver el incidente.", "error");
        }
    });

    // Create Rule HOT-LINK from Resolve Modal
    btnResolveCreateRule.addEventListener("click", () => {
        isCreatingRuleFromResolve = true;
        // Pre-fill the rule pattern if there are logs loaded
        const currentInc = incidents.find(inc => inc.id === parseInt(fieldResolveIncidentId.value));
        
        openRuleModal();
        
        // Auto-fill suggested pattern from app name if possible
        if (currentInc) {
            fieldDescription.value = `Solución para error en ${currentInc.apps.join(", ")}`;
            // Extract a clean piece of the log message to suggest as pattern
            for (const logsList of Object.values(currentInc.logs)) {
                if (logsList.length > 0) {
                    const cleanMsg = logsList[0].message.replace(/[0-9]+|[\w-]{10,}/g, "").substring(0, 45).trim();
                    fieldPattern.value = cleanMsg || logsList[0].message.substring(0, 30);
                    break;
                }
            }
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
            
            if (isCreatingRuleFromResolve) {
                // If created from Resolution flow, re-load resolution select and select this rule
                await fetchKbRulesForResolveDropdown();
                fieldResolveKbRule.value = payload.pattern;
                isCreatingRuleFromResolve = false;
            } else {
                fetchKbRules();
            }
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
