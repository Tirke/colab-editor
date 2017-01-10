#!/usr/bin/env python
# coding=utf-8


import argparse
import codecs
import json
import os
import random
import select
import socket
import sys

import diff_match_patch as dmp

import constants as const

SOCKET_LIST = []  # List of all sockets
USERS = {}  # Dict of all Username:Color

# Declaration of console arguments
parser = argparse.ArgumentParser(
        description="Création du serveur local permettant l'édition du fichier déclaré en argument.")
parser.add_argument('-d', required=True, help="Le nom du fichier concerné par l'édition collaborative",
                    metavar="FICHIER")


# Main function
def document_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Server socket
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Reusable socket address and port
    try:
        server_socket.bind((const.HOST, const.PORT))
    except socket.error:
        print "Socket binding failed"
        sys.exit()

    server_socket.listen(5)  # Up to 5 simultaneous connection tentative

    SOCKET_LIST.append(server_socket)  # Server socket is listed too

    print "Document editing server started on {0}:{1} on file {2}".format(const.HOST, const.PORT, path)

    while 1:
        # Get all sockets ready to be read from non blocking select call
        ready_to_read, ready_to_write, in_error = select.select(SOCKET_LIST, [], [])

        for sock_to_read in ready_to_read:

            if sock_to_read == server_socket:  # New client wants to connect
                sockfd, addr = server_socket.accept()
                SOCKET_LIST.append(sockfd)  # Accept client and add to socket list
                print "Client {0} connected".format(addr)

            else:  # New message from client
                try:
                    data = sock_to_read.recv(const.RECV_BUFFER)  # Read data from socket

                    if data:
                        message = json.loads(data)

                        if message['code'] == const.EDITOR_CHANGE:  # Act according to message code

                            with open(path, 'r+', encoding='utf-8') as f:
                                # Read file, patch file with new data, broadcast patch
                                current_data = f.read()
                                data = message['data']
                                patch = differ.patch_make(current_data, data)
                                result = differ.patch_apply(patch, current_data)
                                broadcast(server_socket, sock_to_read,
                                          json.dumps({'code': const.NEW_PATCH, 'data': differ.patch_toText(patch)}))
                                delete_file_content(f)
                                f.write(result[0])

                        elif message['code'] == const.EMPTY_EDITOR:
                            # Empty file and broadcast
                            open(path, 'w').close()
                            broadcast(server_socket, sock_to_read, json.dumps({'code': const.EMPTY_EDITOR}))

                        elif message['code'] == const.CLIENT_CONNECTION:
                            # Attribute username and color to new client
                            username_ = message['username']

                            while username_ in USERS:
                                username_ += '{:03d}'.format(random.randrange(1, 999))

                            USERS[username_] = random_color()

                            # Send username, current users , and file data to new user
                            with open(path, 'r+') as f:
                                sock_to_read.send(json.dumps({'code': const.CLIENT_CONNECTION,
                                                              'data': f.read(),
                                                              'users': USERS,
                                                              'client_username': username_}))

                            # Notify other clients that a new client connected
                            broadcast(server_socket, sock_to_read,
                                      json.dumps({
                                          'code': const.NEW_CLIENT,
                                          'username': username_,
                                          'color': USERS[username_]
                                      }))

                        elif message['code'] == const.CLIENT_DISCONNECT:
                            # Remove client from list and broadcast disconnection
                            USERS.pop(message['username'])
                            broadcast(server_socket, sock_to_read,
                                      json.dumps({'code': const.CLIENT_DISCONNECT, 'username': message['username']}))

                    else:
                        print 'Client disconnected'
                        if sock_to_read in SOCKET_LIST:
                            SOCKET_LIST.remove(sock_to_read)

                except socket.error:
                    broadcast(server_socket, sock_to_read, json.dumps({'code': const.CLIENT_DISCONNECT}))
                    continue


# Send a message only to peer sockets
def broadcast(server_socket, sock_to_read, message):
    for sock in SOCKET_LIST:
        if sock != server_socket and sock != sock_to_read:
            try:
                sock.send(message)
            except socket.error:
                print 'Broken socket'
                sock.close()
                if sock in SOCKET_LIST:
                    SOCKET_LIST.remove(sock)


# Pick a random color from all Tkinter colors
def random_color():
    return random.choice(const.COLORS)


# Delete a content of a file
def delete_file_content(file_to_edit):
    file_to_edit.seek(0)
    file_to_edit.truncate()


# Open a file with codecs module, allowing specification of the encoding
def open(file, mode='r', buffering=-1, encoding=None,
         errors=None, newline=None, closefd=True, opener=None):
    return codecs.open(filename=file, mode=mode, encoding=encoding,
                       errors=errors, buffering=buffering)


if __name__ == "__main__":
    args = parser.parse_args()
    path = os.getcwd() + '/' + args.d
    if not os.path.exists(path):
        open(path, 'w').close()
    differ = dmp.diff_match_patch()
    sys.exit(document_server())
