import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dbus from "dbus-next";
import { loopStatus, metadataFromStatus, mprisVolume, playbackStatus, statusSignature } from "./mpris-map.js";

const { Interface, ACCESS_READ, ACCESS_READWRITE } = dbus.interface;
const { Variant } = dbus;

function uiPath() {
  return process.env.MUSIC_PLAYER_UI || path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "music-player");
}

function raiseUi() {
  const child = spawn("/usr/bin/python3", [uiPath()], {
    detached: true,
    stdio: "ignore",
  });
  child.unref();
}

function variants(meta) {
  return {
    "mpris:trackid": new Variant("o", meta["mpris:trackid"]),
    "mpris:length": new Variant("x", meta["mpris:length"]),
    "mpris:artUrl": new Variant("s", meta["mpris:artUrl"]),
    "xesam:title": new Variant("s", meta["xesam:title"]),
    "xesam:artist": new Variant("as", meta["xesam:artist"]),
    "xesam:album": new Variant("s", meta["xesam:album"]),
    "xesam:url": new Variant("s", meta["xesam:url"]),
  };
}

export async function startMpris(player, { onQuit } = {}) {
  const bus = dbus.sessionBus();
  class RootIface extends Interface {
    constructor() {
      super("org.mpris.MediaPlayer2");
      this.CanQuit = true;
      this.CanRaise = true;
      this.HasTrackList = false;
      this.Identity = "Music";
      this.DesktopEntry = "music-player";
      this.SupportedUriSchemes = ["https", "http"];
      this.SupportedMimeTypes = ["audio/mpeg", "audio/mp4"];
    }

    Raise() {
      raiseUi();
    }

    Quit() {
      if (onQuit) {
        onQuit();
      }
    }
  }
  RootIface.configureMembers({
    methods: { Raise: {}, Quit: {} },
    properties: {
      CanQuit: { signature: "b", access: ACCESS_READ },
      CanRaise: { signature: "b", access: ACCESS_READ },
      HasTrackList: { signature: "b", access: ACCESS_READ },
      Identity: { signature: "s", access: ACCESS_READ },
      DesktopEntry: { signature: "s", access: ACCESS_READ },
      SupportedUriSchemes: { signature: "as", access: ACCESS_READ },
      SupportedMimeTypes: { signature: "as", access: ACCESS_READ },
    },
  });

  class PlayerIface extends Interface {
    constructor() {
      super("org.mpris.MediaPlayer2.Player");
      this.PlaybackStatus = "Stopped";
      this.LoopStatus = "None";
      this.Rate = 1.0;
      this.Shuffle = false;
      this.Metadata = variants(metadataFromStatus({}));
      this.Volume = 0.7;
      this.Position = 0;
      this.MinimumRate = 1.0;
      this.MaximumRate = 1.0;
      this.CanGoNext = true;
      this.CanGoPrevious = true;
      this.CanPlay = true;
      this.CanPause = true;
      this.CanSeek = true;
      this.CanControl = true;
    }

    async Next() {
      await player.next();
    }

    async Previous() {
      await player.prev();
    }

    async Pause() {
      await player.pause();
    }

    async PlayPause() {
      await player.toggle();
    }

    async Stop() {
      await player.stop();
    }

    async Play() {
      await player.play();
    }

    async Seek(offset) {
      const st = await player.status();
      await player.seek((st.position || 0) + Number(offset) / 1_000_000);
    }

    async SetPosition(_trackId, position) {
      await player.seek(Number(position) / 1_000_000);
    }

    OpenUri(_uri) {}
  }
  PlayerIface.configureMembers({
    methods: {
      Next: {},
      Previous: {},
      Pause: {},
      PlayPause: {},
      Stop: {},
      Play: {},
      Seek: { inSignature: "x" },
      SetPosition: { inSignature: "ox" },
      OpenUri: { inSignature: "s" },
    },
    properties: {
      PlaybackStatus: { signature: "s", access: ACCESS_READ },
      LoopStatus: { signature: "s", access: ACCESS_READWRITE },
      Rate: { signature: "d", access: ACCESS_READ },
      Shuffle: { signature: "b", access: ACCESS_READWRITE },
      Metadata: { signature: "a{sv}", access: ACCESS_READ },
      Volume: { signature: "d", access: ACCESS_READWRITE },
      Position: { signature: "x", access: ACCESS_READ },
      MinimumRate: { signature: "d", access: ACCESS_READ },
      MaximumRate: { signature: "d", access: ACCESS_READ },
      CanGoNext: { signature: "b", access: ACCESS_READ },
      CanGoPrevious: { signature: "b", access: ACCESS_READ },
      CanPlay: { signature: "b", access: ACCESS_READ },
      CanPause: { signature: "b", access: ACCESS_READ },
      CanSeek: { signature: "b", access: ACCESS_READ },
      CanControl: { signature: "b", access: ACCESS_READ },
    },
    signals: { Seeked: { signature: "x" } },
  });

  const root = new RootIface();
  const ctl = new PlayerIface();
  bus.export("/org/mpris/MediaPlayer2", root);
  bus.export("/org/mpris/MediaPlayer2", ctl);
  await bus.requestName("org.mpris.MediaPlayer2.Music");

  let lastSig = "";
  const tick = async () => {
    try {
      const st = await player.status();
      const sig = statusSignature(st);
      ctl.Position = Math.round(Number(st.position || 0) * 1_000_000);
      if (sig === lastSig) {
        return;
      }
      lastSig = sig;
      ctl.PlaybackStatus = playbackStatus(st.state);
      ctl.LoopStatus = loopStatus(st.repeat);
      ctl.Shuffle = Boolean(st.shuffle);
      ctl.Volume = mprisVolume(st.volume);
      ctl.Metadata = variants(metadataFromStatus(st));
      Interface.emitPropertiesChanged(ctl, {
        PlaybackStatus: ctl.PlaybackStatus,
        LoopStatus: ctl.LoopStatus,
        Shuffle: ctl.Shuffle,
        Volume: ctl.Volume,
        Metadata: ctl.Metadata,
      });
    } catch {
      /* player busy */
    }
  };
  const timer = setInterval(tick, 500);
  await tick();
  return () => {
    clearInterval(timer);
    try {
      bus.disconnect();
    } catch {
      /* ignore */
    }
  };
}
