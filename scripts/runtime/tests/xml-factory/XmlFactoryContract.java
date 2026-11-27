import java.io.*;
import java.nio.charset.StandardCharsets;
import org.xmlpull.v1.*;

/** Real canonical XML parser/serializer roundtrip and retained legacy callers. */
public final class XmlFactoryContract {
    private static int checks;
    private static void check(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
        checks++;
    }
    private static final class LegacyFactory extends XmlPullParserFactory {
        LegacyFactory() throws Exception {
            parserClasses.clear(); serializerClasses.clear();
            parserClasses.add(Class.forName("org.kxml2.io.KXmlParser"));
            serializerClasses.add(Class.forName("org.kxml2.io.KXmlSerializer"));
        }
    }
    private static void roundtrip(XmlPullParserFactory factory, String prefix) throws Exception {
        factory.setNamespaceAware(true);
        check(factory.isNamespaceAware(), "factory namespace setting");
        XmlPullParser parser = factory.newPullParser();
        XmlSerializer serializer = factory.newSerializer();
        check(parser.getClass().getName().equals(prefix+".KXmlParser"), "actual parser class ownership");
        check(serializer.getClass().getName().equals(prefix+".KXmlSerializer"), "actual serializer class ownership");
        check(parser.getClass().getClassLoader()==Object.class.getClassLoader()
                        && serializer.getClass().getClassLoader()==Object.class.getClassLoader(),
                "both implementations boot owned");
        check(parser.getFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES), "feature applied to actual parser");
        StringWriter writer = new StringWriter();
        serializer.setOutput(writer); serializer.startDocument("UTF-8", true);
        serializer.setPrefix("p", "urn:contract");
        serializer.startTag("urn:contract", "root");
        serializer.attribute("", "note", "a&b<\"c");
        serializer.text("你好 & < >");
        serializer.startTag("urn:contract", "empty"); serializer.endTag("urn:contract", "empty");
        serializer.endTag("urn:contract", "root"); serializer.endDocument(); serializer.flush();
        String document = writer.toString();
        check(document.contains("&amp;") && document.contains("&lt;"), "actual escaping");
        parser.setInput(new ByteArrayInputStream(document.getBytes(StandardCharsets.UTF_8)), "UTF-8");
        check(parser.getEventType()==XmlPullParser.START_DOCUMENT, "initial event");
        check(parser.nextTag()==XmlPullParser.START_TAG, "root start");
        check(parser.getName().equals("root") && parser.getNamespace().equals("urn:contract"), "root namespace");
        check(parser.getAttributeValue("", "note").equals("a&b<\"c"), "attribute roundtrip");
        check(parser.next()==XmlPullParser.TEXT && parser.getText().equals("你好 & < >"), "Unicode text roundtrip");
        check(parser.nextTag()==XmlPullParser.START_TAG && parser.getName().equals("empty"), "empty start");
        check(parser.isEmptyElementTag(), "empty tag metadata");
        check(parser.nextTag()==XmlPullParser.END_TAG && parser.getName().equals("empty"), "empty end");
        check(parser.nextTag()==XmlPullParser.END_TAG && parser.getName().equals("root"), "root end");
        check(parser.next()==XmlPullParser.END_DOCUMENT, "document complete");
        XmlPullParser broken=factory.newPullParser(); broken.setInput(new StringReader("<root><child></root>"));
        try {
            while(broken.next()!=XmlPullParser.END_DOCUMENT) {}
            throw new AssertionError("malformed nesting accepted");
        } catch(XmlPullParserException expected) { checks++; }
        XmlPullParser cdata=factory.newPullParser(); cdata.setInput(new StringReader("<r><![CDATA[a<&b]]></r>"));
        check(cdata.nextTag()==XmlPullParser.START_TAG, "CDATA root");
        check(cdata.nextToken()==XmlPullParser.CDSECT && cdata.getText().equals("a<&b"), "real CDATA token");
    }
    public static void run() throws Exception {
        for(XmlPullParserFactory factory:new XmlPullParserFactory[]{XmlPullParserFactory.newInstance(),
                XmlPullParserFactory.newInstance(null,null),
                XmlPullParserFactory.newInstance("unused.invalid.Implementation",XmlFactoryContract.class)}) {
            roundtrip(factory,"com.android.org.kxml2.io");
        }
        roundtrip(new LegacyFactory(),"org.kxml2.io");
        XmlPullParserFactory factory=XmlPullParserFactory.newInstance();
        factory.setFeature("urn:unknown:contract",false);
        check(factory.newPullParser()!=null,"false unsupported feature is not applied");
        factory.setFeature("urn:unknown:contract",true);
        try { factory.newPullParser(); throw new AssertionError("unsupported true feature ignored"); }
        catch(XmlPullParserException expected) { checks++; }
        System.out.println("XML_FACTORY_CONTRACT=PASS|checks="+checks
                +"|canonical_default=true|real_roundtrip=true|malformed_rejected=true|legacy_classes_retained=true");
    }
}
