/* echo-ms-explorer — plate grid interactivity
 *
 * Manages click/shift-click selection on the 384-well grid and pushes the
 * current selection back to Shiny as input.plate_selection (array of well IDs).
 * Supports 96, 384, and 1536-well plates (row labels A–AF).
 */

(function () {
  // Row labels matching the Python ROW_LETTERS list
  const ROW_LABELS = [
    "A","B","C","D","E","F","G","H",
    "I","J","K","L","M","N","O","P",
    "Q","R","S","T","U","V","W","X",
    "Y","Z","AA","AB","AC","AD","AE","AF",
  ];
  const ROW_INDEX = {};
  ROW_LABELS.forEach((lbl, i) => (ROW_INDEX[lbl] = i));

  function parseWell(w) {
    const m = w.match(/^([A-Z]{1,2})(\d+)$/);
    if (!m) return null;
    const rowIdx = ROW_INDEX[m[1]];
    if (rowIdx === undefined) return null;
    return { row: rowIdx, col: parseInt(m[2]) - 1, label: m[1], well: w };
  }

  let lastClickedWell = null;
  let pendingSelection = new Set();

  // Receive a "set selection" command from the server
  Shiny.addCustomMessageHandler("plate_set_selection", function (data) {
    pendingSelection = new Set(data.wells || []);
    syncDomFromState();
    sendSelectionToShiny();
  });

  // Receive plate dimensions from server and current selection
  Shiny.addCustomMessageHandler("plate_init", function (data) {
    pendingSelection = new Set(data.selected || []);
    setTimeout(syncDomFromState, 10);
  });

  function syncDomFromState() {
    document.querySelectorAll(".plate-cell").forEach((cell) => {
      const well = cell.dataset.well;
      if (pendingSelection.has(well)) {
        cell.classList.add("selected");
      } else {
        cell.classList.remove("selected");
      }
    });
    updateSequenceNumbers();
  }

  function updateSequenceNumbers() {
    const wellList = Array.from(pendingSelection);
    if (wellList.length === 0) {
      document.querySelectorAll(".plate-cell .seq-num").forEach((el) => el.remove());
      return;
    }

    const parsed = wellList.map(parseWell).filter(Boolean);

    // Group by row, sort by col, alternate direction (serpentine)
    const rowsPresent = [...new Set(parsed.map((p) => p.row))].sort((a, b) => a - b);
    const ordered = [];
    rowsPresent.forEach((r, offset) => {
      const wellsInRow = parsed
        .filter((p) => p.row === r)
        .sort((a, b) => (offset % 2 === 0 ? a.col - b.col : b.col - a.col));
      wellsInRow.forEach((p) => ordered.push(p.well));
    });

    const seqMap = {};
    ordered.forEach((w, i) => (seqMap[w] = i + 1));

    document.querySelectorAll(".plate-cell").forEach((cell) => {
      let seq = cell.querySelector(".seq-num");
      const num = seqMap[cell.dataset.well];
      if (num !== undefined) {
        if (!seq) {
          seq = document.createElement("span");
          seq.className = "seq-num";
          cell.appendChild(seq);
        }
        seq.textContent = num;
      } else if (seq) {
        seq.remove();
      }
    });
  }

  function sendSelectionToShiny() {
    Shiny.setInputValue("plate_selection", Array.from(pendingSelection), {
      priority: "event",
    });
  }

  // Delegated click handler on document so it survives DOM re-renders
  document.addEventListener("click", function (e) {
    const cell = e.target.closest(".plate-cell");
    if (!cell) return;
    const well = cell.dataset.well;
    if (!well) return;

    if (e.shiftKey && lastClickedWell) {
      const p1 = parseWell(lastClickedWell);
      const p2 = parseWell(well);
      if (p1 && p2 && p1.row === p2.row) {
        // Same-row range select
        const lo = Math.min(p1.col, p2.col);
        const hi = Math.max(p1.col, p2.col);
        for (let c = lo; c <= hi; c++) {
          pendingSelection.add(`${p1.label}${c + 1}`);
        }
      } else if (p1 && p2) {
        // Cross-row rectangle select
        const rLo = Math.min(p1.row, p2.row);
        const rHi = Math.max(p1.row, p2.row);
        const cLo = Math.min(p1.col, p2.col);
        const cHi = Math.max(p1.col, p2.col);
        for (let r = rLo; r <= rHi; r++) {
          for (let c = cLo; c <= cHi; c++) {
            pendingSelection.add(`${ROW_LABELS[r]}${c + 1}`);
          }
        }
      }
    } else {
      // Single toggle
      if (pendingSelection.has(well)) {
        pendingSelection.delete(well);
      } else {
        pendingSelection.add(well);
      }
      lastClickedWell = well;
    }

    syncDomFromState();
    sendSelectionToShiny();
  });
})();
