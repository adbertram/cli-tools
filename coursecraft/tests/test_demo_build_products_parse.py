from coursecraft_cli.commands.demo_build_products import parse_xml_build_product


def test_demo_build_product_parser_accepts_direct_requirement_items(tmp_path):
    xml_path = tmp_path / "demo-voice-recording.xml"
    xml_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<build-product>
  <metadata>
    <name>Demo Voice Recording</name>
  </metadata>
  <description>Generated demo narration.</description>
  <requirements>
    <item>Read the demo record.</item>
    <item>Generate audio with ElevenLabs.</item>
  </requirements>
</build-product>
""",
        encoding="utf-8",
    )

    fields = parse_xml_build_product(xml_path)

    assert fields["Requirements"] == "- Read the demo record.\n- Generate audio with ElevenLabs."
