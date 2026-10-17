// Layout-only browser probe. Inspect every row, including offscreen rows in a
// local scroller: document overflow alone cannot detect content crossing dividers.
export const listGeometry = (page) =>
  page.evaluate(() => {
    const rows = [...document.querySelectorAll(".ui02-list-item")];
    const violations = [];
    const sizes = [];
    for (const [index, row] of rows.entries()) {
      const r = row.getBoundingClientRect();
      const style = getComputedStyle(row);
      const bounds = {
        left:
          r.left +
          parseFloat(style.borderLeftWidth) +
          parseFloat(style.paddingLeft),
        right:
          r.right -
          parseFloat(style.borderRightWidth) -
          parseFloat(style.paddingRight),
        top:
          r.top +
          parseFloat(style.borderTopWidth) +
          parseFloat(style.paddingTop),
        bottom:
          r.bottom -
          parseFloat(style.borderBottomWidth) -
          parseFloat(style.paddingBottom),
      };
      sizes.push({
        index,
        height: r.height,
        contentHeight: bounds.bottom - bounds.top,
      });
      for (const child of row.children) {
        const c = child.getBoundingClientRect();
        if (!c.width || !c.height) continue;
        const overrun = {
          left: bounds.left - c.left,
          right: c.right - bounds.right,
          top: bounds.top - c.top,
          bottom: c.bottom - bounds.bottom,
        };
        if (Object.values(overrun).some((value) => value > 1)) {
          violations.push({ index, child: child.className, overrun });
        }
      }
      const next = row.nextElementSibling;
      if (
        next?.matches(".ui02-list-item") &&
        r.bottom > next.getBoundingClientRect().top + 1
      ) {
        violations.push({
          index,
          issue: "Row border intersects following row",
        });
      }
      // A row-wide overflow:hidden patch would hide the symptom, not fix sizing.
      if (["hidden", "clip"].includes(style.overflowY)) {
        violations.push({ index, issue: "Row clips its content" });
      }
    }
    return {
      rows: rows.length,
      sizes,
      violations,
      documentOverflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
