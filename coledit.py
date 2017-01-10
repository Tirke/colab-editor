#!/usr/bin/env python
# coding=utf-8

import Queue
import ScrolledText
import Tkinter as tk
import argparse
import codecs
import hashlib
import json
import select
import socket
import sys
import threading
import tkMessageBox
from tkFileDialog import asksaveasfilename

import constants as const
import diff_match_patch as dmp

parser = argparse.ArgumentParser(
        description="Lancement d'un éditeur client permettant l'édition collaborative d'un document")
parser.add_argument('-p', required=True, help="Le pseudo de l'utilisateur voulant se connecter",
                    metavar="PSEUDO")


class ReceiverThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition."""

    def __init__(self, queue, *args, **kwargs):
        super(ReceiverThread, self).__init__(*args, **kwargs)
        self._stop = threading.Event()  # Flag for stoppable Thread
        self.queue = queue

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()


class BasicEditor:
    FONT_SIZE = 10

    def __init__(self, master, connexion, username):
        self.master = master
        master.title("Collaborative Editor")
        master.protocol("WM_DELETE_WINDOW", lambda: self.on_close())  # Closing routine
        master.createcommand('exit', lambda: self.on_close())  # Closing routine

        self.connexion = connexion
        self.username = username

        self.differ = dmp.diff_match_patch()

        self.menubar = tk.Menu(master)

        menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=menu)
        menu.add_command(label="Save", command=lambda: self.save())

        self.master.config(menu=self.menubar)
        self.master.bind('<Control-a>', lambda event: self.select_all(event))

        self.textarea = ScrolledText.ScrolledText(master, height=10, wrap=tk.WORD)
        self.signature = self.get_signature()

        self.user_labels_frame = tk.LabelFrame(master, text='Users', padx=5, pady=5, height=10)
        self.user_list = {}

        self.queue = Queue.Queue()
        self.thread = ReceiverThread(self.queue, target=self.watch_socket)
        self.thread.start()
        self.process_queue()
        master.after(500, self.send_to_socket)

        # LAYOUT

        self.textarea.grid(row=0, column=0, sticky=tk.N + tk.E + tk.S + tk.W)
        self.user_labels_frame.grid(row=0, column=1, sticky=tk.N)

    # GUI METHODS

    # GUI thread process queue and potentially modify GUI every 100 ms
    def process_queue(self):
        try:
            data = self.queue.get(0)
            message = json.loads(data)
            code_ = message['code']

            if code_ == const.CLIENT_CONNECTION:
                self.replace_text(message['data'])
                self.signature = self.get_signature()
                self.username = message['client_username']
                self.create_user_list(message['users'])
                print 'Connected on {0}:{1} with username {2}'.format(const.HOST, const.PORT, self.username)
            elif code_ == const.NEW_CLIENT:
                self.add_user(message['username'], message['color'])
            elif code_ == const.CLIENT_DISCONNECT:
                self.remove_user(message['username'])
            elif code_ == const.NEW_PATCH and message['data']:
                patch = self.differ.patch_fromText(message['data'])
                self.replace_text(self.differ.patch_apply(patch, self.get_all_text())[0])
                self.signature = self.get_signature()
            elif code_ == const.EMPTY_EDITOR:
                self.delete_all_text()

            self.master.after(100, self.process_queue)

        except Queue.Empty:
            self.master.after(100, self.process_queue)

    # Send data to socket if text widget content has changed (every 500ms)
    def send_to_socket(self):
        if self.signature != self.get_signature():
            data = self.get_all_text().encode('utf-8')
            if data:
                self.connexion.send(
                        json.dumps({'code': const.EDITOR_CHANGE, 'data': self.get_all_text().encode('utf-8')}))
            else:
                self.connexion.send(json.dumps({'code': const.EMPTY_EDITOR}))

        self.master.after(500, self.send_to_socket)

    # Return all text from text widget without the last (useless) linefeed
    def get_all_text(self):
        return self.textarea.get(1.0, tk.END)[:-1]

    # Hash the text widget content
    def get_signature(self):
        return hashlib.md5(self.get_all_text().encode('utf-8')).digest()

    # Delete all text from widget
    def delete_all_text(self):
        self.textarea.delete(1.0, tk.END)

    # Delete and replace text in widget
    def replace_text(self, new_text):
        self.delete_all_text()
        self.textarea.insert(tk.END, new_text)

    # Save a local version of the file
    def save(self):
        filename = asksaveasfilename(parent=self.master, defaultextension='.txt', title='Save file as')
        if filename:
            with codecs.open(filename, 'w', encoding='utf-8') as f:
                f.write(self.get_all_text())

    def select_all(self, event=None):
        self.textarea.tag_add(tk.SEL, '1.0', tk.END + '-1c')
        self.textarea.mark_set(tk.INSERT, '1.0')
        self.textarea.see(tk.INSERT)

    # Initialize user list when new client connects
    def create_user_list(self, usr_list):
        for user in usr_list:
            self.add_user(user, usr_list[user])

    # Add a user (as a label) to the user list
    def add_user(self, usrname, color):
        label = tk.Label(self.user_labels_frame, text=usrname, bg=color, font=("Times", self.FONT_SIZE, "bold"))
        self.user_list[usrname] = label
        label.pack()

    # Remove a user from list, eg when a client is disconnected
    def remove_user(self, usrname):
        label = self.user_list.pop(usrname)
        label.destroy()

    # Gracefully close thread, connection and destroy window on editor shutdown
    def on_close(self):
        self.connexion.send(json.dumps({'code': const.CLIENT_DISCONNECT, 'username': self.username}))
        self.thread.stop()
        self.connexion.close()
        self.master.destroy()

    # SOCKET DATA HANDLING

    # Thread function to fetch data from socket and feed it to the shared Queue
    def watch_socket(self):
        socket_list = [client_socket]
        while not self.thread.stopped():
            try:
                ready_to_read, ready_to_write, in_error = select.select(socket_list, [], [])
                for sock_to_read in ready_to_read:
                    try:
                        # receiving data from the server
                        data = sock_to_read.recv(const.RECV_BUFFER)
                        if data:
                            self.queue.put(data)
                        else:  # remove the socket that's broken
                            if sock_to_read in socket_list:
                                socket_list.remove(sock_to_read)
                                self.thread.stop()
                                tkMessageBox.showerror('Server down', 'Socket connection to server closed')
                    except socket.error:
                        print 'Not expected socket error'
                        sys.exit(1)
            except select.error:
                print 'Connection with server shutdown'


if __name__ == '__main__':
    args = parser.parse_args()
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(2)

    try:
        client_socket.connect((const.HOST, const.PORT))
        client_socket.send(json.dumps({'code': const.CLIENT_CONNECTION, 'username': args.p}))
    except socket.error:
        print 'Unable to open socket at {0}:{1}'.format(const.HOST, const.PORT)
        sys.exit()

    # Tkinter window initialization
    root = tk.Tk()
    tk.Grid.rowconfigure(root, 0, weight=1)
    tk.Grid.columnconfigure(root, 0, weight=1)
    editor = BasicEditor(root, client_socket, args.p)
    root.mainloop()
