export function likeStatusFromInfo(info) {
  const basic = info?.basic_info || {};
  const status = String(basic.like_status || basic.likeStatus || info?.like_status || "").toUpperCase();
  if (basic.is_liked === true || status === "LIKE") {
    return { liked: true, disliked: false };
  }
  if (basic.is_disliked === true || status === "DISLIKE") {
    return { liked: false, disliked: true };
  }
  if (status === "INDIFFERENT" || basic.is_liked === false || basic.is_disliked === false) {
    return { liked: false, disliked: false };
  }
  return { liked: null, disliked: null };
}

export async function rateTrack({ execute, videoId, liked }) {
  const id = String(videoId || "").trim();
  if (!id) {
    throw new Error("track id is required");
  }
  if (typeof execute !== "function") {
    throw new Error("like is not available");
  }
  const endpoint = liked ? "/like/like" : "/like/removelike";
  const resp = await execute(endpoint, { target: { videoId: id }, client: "YTMUSIC" });
  if (resp && resp.success === false) {
    throw new Error(liked ? "could not like this track" : "could not unlike this track");
  }
  return { id, liked: Boolean(liked), disliked: false };
}

export function mergeLikeStatus(videoId, likedIds, fromInfo = {}) {
  const id = String(videoId || "").trim();
  if (id && likedIds && typeof likedIds.has === "function" && likedIds.has(id)) {
    return { liked: true, disliked: false };
  }
  return {
    liked: fromInfo.liked ?? null,
    disliked: fromInfo.disliked ?? null,
  };
}
