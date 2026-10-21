/**
 * web/room.html: the public Kennel Room, the LINEHOUND house pack and the Claude Hound at work. The page owns only the mount point; the room
 * (room-scene.js) reads the same public endpoints as the leaderboard (room-data.js loadHouse) and polls them every 45 seconds while the tab is visible.
 */

import { mountRoom } from "./room-scene.js";

const host = document.querySelector("[data-hook='room-mount']");
export const room = host ? mountRoom(host, { scope: "house" }) : null;
