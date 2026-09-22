import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;

/** Persistent wrapper around this device's ordinary /system/bin/input class.
 * No app hooks, private game calls, pixels, or network protocol injection.
 * Protocol: sequence T x y | sequence S x y x y duration | sequence P.
 * EOF, malformed commands, injection errors and a fixed lifetime terminate it.
 */
public final class HalcyonInput {
    public static void main(String[] ignored) throws Exception {
        Thread watchdog = new Thread(() -> {
            try { Thread.sleep(2700000); } catch (InterruptedException e) { return; }
            System.exit(3);
        });
        watchdog.setDaemon(true);
        watchdog.start();
        Method input = Class.forName("com.android.commands.input.Input")
            .getMethod("main", String[].class);
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        System.out.println("HALCYON_INPUT_V1");
        System.out.flush();
        String line;
        long previous = 0;
        while ((line = reader.readLine()) != null) {
            if (line.length() > 160) throw new IllegalArgumentException("command too long");
            String[] words = line.split(" ");
            long sequence = Long.parseLong(words[0]);
            if (sequence != previous + 1) throw new IllegalArgumentException("sequence changed");
            String[] command;
            if (words.length == 2 && words[1].equals("P")) {
                command = null;
            } else if (words.length == 4 && words[1].equals("T")) {
                point(words[2], words[3]);
                command = new String[] {"touchscreen", "tap", words[2], words[3]};
            } else if (words.length == 7 && words[1].equals("S")) {
                point(words[2], words[3]); point(words[4], words[5]);
                int duration = Integer.parseInt(words[6]);
                if (duration < 1 || duration > 2000) throw new IllegalArgumentException("duration");
                command = new String[] {"touchscreen", "swipe", words[2], words[3], words[4], words[5], words[6]};
            } else throw new IllegalArgumentException("invalid command");
            long started = System.nanoTime();
            if (command != null) input.invoke(null, (Object) command);
            long ended = System.nanoTime();
            System.out.println("DONE " + sequence + " " + started + " " + ended);
            System.out.flush();
            previous = sequence;
        }
    }

    private static void point(String x, String y) {
        int px = Integer.parseInt(x), py = Integer.parseInt(y);
        if (px < 0 || px >= 960 || py < 0 || py >= 540)
            throw new IllegalArgumentException("unqualified viewport coordinate");
    }
}
