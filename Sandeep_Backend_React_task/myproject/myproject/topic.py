# from confluent_kafka.admin import AdminClient, NewTopic
# import sys

# # Kafka broker - use PLAINTEXT listener for testing
# bootstrap_server = "127.0.0.1:12091"  # CLEAR listener

# # Create AdminClient
# admin_client = AdminClient({"bootstrap.servers": bootstrap_server})

# # Topic configuration
# topic_name = "topicReq1810"
# num_partitions = 1
# replication_factor = 1

# # Create a NewTopic object
# new_topic = NewTopic(topic_name, num_partitions=num_partitions, replication_factor=replication_factor)

# # Call create_topics
# fs = admin_client.create_topics([new_topic])

# # Wait for operation to finish and check results
# for topic, f in fs.items():
#     try:
#         f.result()  # The result itself is None if successful
#         print(f"Topic '{topic}' created successfully!")
#     except Exception as e:
#         print(f"Failed to create topic '{topic}': {e}")
