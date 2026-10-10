// Read-only Java activity/view state. No hooks or generated game input.
import Java from 'frida-java-bridge';

function snapshot() {
    const Thread = Java.use('android.app.ActivityThread');
    const Record = Java.use('android.app.ActivityThread$ActivityClientRecord');
    const items = Thread.currentActivityThread().mActivities.value.values().toArray();
    if (items.length > 8) throw Error('activity registry bound');
    const rows = [];
    for (const item of items) {
        const entry = Java.cast(item, Record), activity = entry.activity.value;
        if (activity === null || activity.$className !== 'com.superevilmegacorp.nuogameentry.NuoActivityGame') continue;
        const owned = Java.cast(activity, Java.use(activity.$className)), view = owned.mViewGL.value;
        if (view === null) throw Error('owned Java view absent');
        rows.push({activity:activity.$className, paused:entry.paused.value,
            initialized:view.isInitialized(), window_focus:view.hasWindowFocus(),
            focused:view.isFocused(), enabled:view.isEnabled()});
    }
    return {guest_wall:Date.now()/1000, rows};
}
rpc.exports.snapshot = () => new Promise((resolve, reject) => Java.perform(() => {
    try { resolve(snapshot()); } catch (error) { reject(error); }
}));
