from datetime import datetime, timezone

from app.services.onvif_client import (
    event_types_for_topics,
    normalize_onvif_event_type,
    parse_event_topics,
    parse_pull_messages,
    parse_subscription,
)


EVENT_PROPERTIES_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tev="http://www.onvif.org/ver10/events/wsdl"
            xmlns:wstop="http://docs.oasis-open.org/wsn/t-1"
            xmlns:tns1="http://www.onvif.org/ver10/topics"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <tev:GetEventPropertiesResponse>
      <tev:TopicSet>
        <tns1:RuleEngine>
          <tns1:CellMotionDetector>
            <tns1:Motion>
              <tt:MessageDescription IsProperty="true"/>
            </tns1:Motion>
          </tns1:CellMotionDetector>
          <tns1:PeopleDetector>
            <tns1:PersonDetected>
              <tt:MessageDescription IsProperty="true"/>
            </tns1:PersonDetected>
          </tns1:PeopleDetector>
        </tns1:RuleEngine>
        <tns1:Device>
          <tns1:Tamper>
            <tt:MessageDescription IsProperty="true"/>
          </tns1:Tamper>
        </tns1:Device>
      </tev:TopicSet>
    </tev:GetEventPropertiesResponse>
  </s:Body>
</s:Envelope>"""

SUBSCRIPTION_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tev="http://www.onvif.org/ver10/events/wsdl"
            xmlns:wsa="http://www.w3.org/2005/08/addressing">
  <s:Body>
    <tev:CreatePullPointSubscriptionResponse>
      <tev:SubscriptionReference>
        <wsa:Address>http://192.0.2.90/onvif/subscription/42</wsa:Address>
      </tev:SubscriptionReference>
      <tev:CurrentTime>2026-09-18T06:30:00Z</tev:CurrentTime>
      <tev:TerminationTime>2026-09-18T06:31:00Z</tev:TerminationTime>
    </tev:CreatePullPointSubscriptionResponse>
  </s:Body>
</s:Envelope>"""

PULL_MESSAGES_XML = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <PullMessagesResponse>
      <wsnt:NotificationMessage>
        <wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">
          tns1:RuleEngine/CellMotionDetector/Motion
        </wsnt:Topic>
        <wsnt:Message>
          <tt:Message UtcTime="2026-09-18T06:30:05Z" PropertyOperation="Changed">
            <tt:Source>
              <tt:SimpleItem Name="VideoSourceConfigurationToken" Value="video-source-1"/>
            </tt:Source>
            <tt:Data>
              <tt:SimpleItem Name="IsMotion" Value="true"/>
            </tt:Data>
          </tt:Message>
        </wsnt:Message>
      </wsnt:NotificationMessage>
      <wsnt:NotificationMessage>
        <wsnt:Topic>vendor:Analytics/People/PersonDetected</wsnt:Topic>
        <wsnt:Message>
          <tt:Message UtcTime="2026-09-18T06:30:06Z">
            <tt:Data>
              <tt:SimpleItem Name="State" Value="1"/>
            </tt:Data>
          </tt:Message>
        </wsnt:Message>
      </wsnt:NotificationMessage>
    </PullMessagesResponse>
  </s:Body>
</s:Envelope>"""


def test_event_properties_expose_known_topics_without_claiming_unknown_capabilities() -> None:
    topics = parse_event_topics(EVENT_PROPERTIES_XML)
    assert "RuleEngine/CellMotionDetector/Motion" in topics
    assert "RuleEngine/PeopleDetector/PersonDetected" in topics
    assert "Device/Tamper" in topics

    assert event_types_for_topics(topics) == ["motion", "person", "tamper"]
    assert normalize_onvif_event_type("vendor:Something/CustomAlarm", {}) == "unknown"


def test_subscription_response_parses_reference_and_expiry() -> None:
    subscription = parse_subscription(SUBSCRIPTION_XML)

    assert subscription.reference_url == "http://192.0.2.90/onvif/subscription/42"
    assert subscription.current_time == datetime(2026, 9, 18, 6, 30, tzinfo=timezone.utc)
    assert subscription.termination_time == datetime(2026, 9, 18, 6, 31, tzinfo=timezone.utc)


def test_pull_messages_normalize_topic_payload_and_activity_state() -> None:
    notifications = parse_pull_messages(PULL_MESSAGES_XML)

    assert [item.event_type for item in notifications] == ["motion", "person"]

    motion = notifications[0]
    assert motion.occurred_at == datetime(2026, 9, 18, 6, 30, 5, tzinfo=timezone.utc)
    assert motion.property_operation == "Changed"
    assert motion.source["VideoSourceConfigurationToken"] == "video-source-1"
    assert motion.data["IsMotion"] == "true"
    assert motion.active is True

    person = notifications[1]
    assert person.data["State"] == "1"
    assert person.active is True
