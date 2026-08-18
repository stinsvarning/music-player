import { textOf } from "./text.js";

export const UNPLAYABLE = "unplayable";

export function unplayableError(detail = "") {
  const extra = String(detail || "").trim();
  const err = new Error(extra ? `can't play this track here (${extra})` : "can't play this track here");
  err.code = UNPLAYABLE;
  return err;
}

export function isUnplayableError(err) {
  if (!err) {
    return false;
  }
  if (err.code === UNPLAYABLE) {
    return true;
  }
  return /can't play this track here|youtube-only|playable_in_embed|error.?1(50|01)\b/i.test(String(err.message || ""));
}

function statusBlob(node) {
  return node?.playability_status || node?.playabilityStatus || {};
}

function reasonOf(node) {
  const status = statusBlob(node);
  return textOf(
    status.reason ||
      status.messages ||
      node?.unplayable_text ||
      node?.reason ||
      "",
  );
}

export function itemLooksUnplayable(item) {
  if (!item) {
    return false;
  }
  if (item.unplayable === true || item.playable === false) {
    return true;
  }
  const status = String(statusBlob(item).status || "").toUpperCase();
  if (status === "UNPLAYABLE" || status === "ERROR" || status === "LOGIN_REQUIRED") {
    return true;
  }
  if (item.playable_in_embed === false || statusBlob(item).playable_in_embed === false) {
    return true;
  }
  return /\b1(50|01)\b|not available|unavailable|restricted|third.?party|can't play/i.test(reasonOf(item));
}

export function infoLooksUnplayable(info) {
  if (!info) {
    return "";
  }
  const status = statusBlob(info);
  if (info.playable_in_embed === false || status.playable_in_embed === false) {
    return reasonOf(info) || "youtube-only";
  }
  if (itemLooksUnplayable(info)) {
    return reasonOf(info) || "unavailable";
  }
  return "";
}
