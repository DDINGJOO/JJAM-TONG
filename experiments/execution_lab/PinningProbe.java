package io.jjamtong.experiment;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import jdk.jfr.Recording;
import jdk.jfr.consumer.RecordingFile;

/** Controlled monitor/sleep input, not a claim about every source of pinning. */
public final class PinningProbe {
    private static final int TASKS = 4;
    private static final int SLEEP_MILLIS = 120;

    private PinningProbe() { }

    private static void pause() throws InterruptedException {
        Thread.sleep(SLEEP_MILLIS);
    }

    private static void monitorPause() throws InterruptedException {
        // Each task owns its lock: contention is not the cause of this input.
        synchronized (new Object()) {
            pause();
        }
    }

    private static void runCase(String label, boolean monitor, Path directory) throws Exception {
        Path recordingPath = directory.resolve(label + ".jfr");
        try (var recording = new Recording()) {
            recording.setMaxSize(32L * 1024 * 1024);
            recording.enable("jdk.VirtualThreadPinned").withThreshold(Duration.ZERO).withStackTrace();
            recording.enable("jdk.VirtualThreadStart");
            recording.enable("jdk.VirtualThreadEnd");
            recording.start();
            try (var executor = Executors.newThreadPerTaskExecutor(
                    Thread.ofVirtual().name("pinning-" + label + "-", 0).factory())) {
                var tasks = new ArrayList<Callable<Boolean>>();
                for (int i = 0; i < TASKS; i++) {
                    tasks.add(() -> {
                        if (monitor) monitorPause(); else pause();
                        return Thread.currentThread().isVirtual();
                    });
                }
                for (var result : executor.invokeAll(tasks)) {
                    if (!result.get()) throw new AssertionError("Probe did not run on a virtual thread");
                }
            }
            recording.stop();
            recording.dump(recordingPath);
        }
        int pinned = 0;
        int monitorPinned = 0;
        int starts = 0;
        int ends = 0;
        for (var event : RecordingFile.readAllEvents(recordingPath)) {
            String name = event.getEventType().getName();
            if (event.getThread() != null
                    && event.getThread().getJavaName().startsWith("pinning-" + label + "-")) {
                if (name.equals("jdk.VirtualThreadStart")) starts++;
                if (name.equals("jdk.VirtualThreadEnd")) ends++;
            }
            if (!name.equals("jdk.VirtualThreadPinned")) continue;
            pinned++;
            if (event.getStackTrace() != null && event.getStackTrace().getFrames().stream().anyMatch(frame ->
                    frame.getMethod().getType().getName().equals(PinningProbe.class.getName())
                    && frame.getMethod().getName().equals("monitorPause"))) {
                monitorPinned++;
            }
        }
        if (starts != TASKS || ends != TASKS) throw new AssertionError("Incomplete VT lifecycle recording");
        System.out.printf("{\"case\":\"%s\",\"tasks\":%d,\"sleepMillis\":%d,"
                + "\"virtualThreadStarts\":%d,\"virtualThreadEnds\":%d,"
                + "\"pinnedEvents\":%d,\"monitorPinnedEvents\":%d}%n",
                label, TASKS, SLEEP_MILLIS, starts, ends, pinned, monitorPinned);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Supply an output directory");
        Path directory = Path.of(args[0]);
        Files.createDirectories(directory);
        // Warm initialization outside the recording, including virtual-thread sleep.
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            executor.submit(() -> { try { pause(); } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException(e);
            } }).get();
        }
        runCase("unlocked-control", false, directory);
        runCase("monitor-sleep", true, directory);
    }
}
