# Copyright (C) 2016  Red Hat, Inc
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Common bus class for Commissaire.
"""

import json
import uuid


class RemoteProcedureCallError(Exception):
    """
    Exception class for remote procedure call errors.
    """
    def __init__(self, message, code=0, data=None):
        """
        Creates a RemoteProcedureCallError instance.

        :param message: Error message.
        :type message: str
        :param code: Error code.
        :type code: int
        :param data: Additional error data.
        :type data: dict
        """
        super(RemoteProcedureCallError, self).__init__(message, code, data)
        self.message = message
        self.code = code
        self.data = data

    def __str__(self):
        """
        Returns a string representation of the error.
        """
        return '({0}) {1}'.format(self.code, self.message)


class BusMixin:
    """
    Common methods for classes which utilize the Commissaire bus.

    The mixed class requires the following:

    :param logger: The class level logger.
    :type logging: logging.Logger
    :param connection: Connection to the bus.
    :type connection: kombu.connection.Connection
    :param producer: Producer instance for sending messages.
    :type producer: kombu.messaging.Producer
    """

    @classmethod
    def create_id(cls):
        """
        Creates a new unique identifier.

        :returns: A unique identification string.
        :rtype: str
        """
        return str(uuid.uuid4())

    def request(self, routing_key, method=None, params={}, **kwargs):
        """
        Sends a request to a simple queue. Requests create the initial response
        queue and wait for a response.

        For convenience, if a method argument is omitted then the last
        segment of the routing_key is used as the method name.

        :param routing_key: The routing key to publish on.
        :type routing_key: str
        :param method: The remote method to request.
        :type method: str
        :param params: Keyword parameters to pass to the remote method.
        :type params: dict
        :param kwargs: Keyword arguments to pass to SimpleQueue
        :type kwargs: dict
        :returns: Result
        :rtype: tuple
        """
        id = self.create_id()
        response_queue_name = 'response-{}'.format(id)
        self.logger.debug('Creating response queue "{}"'.format(
            response_queue_name))
        queue_opts = {
            'auto_delete': True,
            'durable': False,
        }
        if kwargs.get('queue_opts'):
            queue_opts.update(kwargs.pop('queue_opts'))

        self.logger.debug('Response queue arguments: {}'.format(kwargs))

        response_queue = self.connection.SimpleQueue(
            response_queue_name,
            queue_opts=queue_opts,
            **kwargs)

        if method is None:
            method = routing_key.split('.')[-1]

        jsonrpc_msg = {
            'jsonrpc': '2.0',
            'id': id,
            'method': method,
            'params': params,
        }
        self.logger.debug('jsonrpc message for id "{}": "{}"'.format(
            id, jsonrpc_msg))

        self.producer.publish(
            jsonrpc_msg,
            routing_key,
            declare=[self._exchange],
            reply_to=response_queue_name)

        self.logger.debug(
            'Sent message id "{}" to "{}". Waiting on response...'.format(
                id, response_queue_name))

        result = response_queue.get(block=True, timeout=10)
        result.ack()

        payload = result.payload
        if isinstance(payload, str):
            payload = json.loads(payload)

        self.logger.debug(
            'Result retrieved from response queue "{}": result="{}"'.format(
                response_queue_name, result))
        self.logger.debug('Closing queue {}'.format(response_queue_name))
        response_queue.close()

        if 'error' in payload:
            error_data = payload['error']
            self.logger.warn(
                'Message "{}" contains error: {}'.format(id, error_data))
            raise RemoteProcedureCallError(
                error_data.get('message', 'Internal error'),
                error_data.get('code', -32603),
                error_data.get('data', {}))

        return payload
