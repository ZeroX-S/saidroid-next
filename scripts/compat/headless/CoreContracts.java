package org.saildroid.compat;

import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import junit.framework.AssertionFailedError;
import junit.framework.Test;
import junit.framework.TestCase;
import junit.framework.TestListener;
import junit.framework.TestResult;
import junit.framework.TestSuite;

/** The same unmodified AOSP libcore tests run on the reference JDK and ART. */
public final class CoreContracts {
    public static void main(String[] arguments) throws Exception {
        TestSuite suite = new TestSuite();
        suite.addTestSuite(org.apache.harmony.tests.java.util.zip.CRC32Test.class);
        suite.addTestSuite(org.apache.harmony.tests.java.util.zip.Adler32Test.class);
        suite.addTestSuite(org.apache.harmony.tests.java.lang.reflect.ArrayTest.class);
        suite.addTestSuite(org.apache.harmony.tests.java.lang.IntegerTest.class);
        final Set<Test> failed = Collections.newSetFromMap(new IdentityHashMap<Test, Boolean>());
        TestResult result = new TestResult();
        result.addListener(new TestListener() {
            private String identity(Test test) {
                return test.getClass().getName() + "#" + ((TestCase) test).getName();
            }
            public void startTest(Test test) {}
            public void endTest(Test test) {
                if (!failed.contains(test)) System.out.println("COMPAT_EVENT=" + identity(test) + "|PASS|");
            }
            public void addFailure(Test test, AssertionFailedError error) {
                failed.add(test);
                System.out.println("COMPAT_EVENT=" + identity(test) + "|FAIL|" + error);
            }
            public void addError(Test test, Throwable error) {
                failed.add(test);
                System.out.println("COMPAT_EVENT=" + identity(test) + "|ERROR|" + error);
                error.printStackTrace();
            }
        });
        suite.run(result);
        System.out.println("COMPAT_SUITE=core|tests=" + result.runCount()
                + "|failures=" + result.failureCount() + "|errors=" + result.errorCount());
        if (result.runCount() != suite.countTestCases() || result.runCount() == 0 || !result.wasSuccessful()) {
            throw new AssertionError("AOSP libcore contract suite failed");
        }
    }
}
