from pkg.mic.sherpa import SherpaListener


def main():
    listener = SherpaListener()
    listener.start()
    for item in listener.listen():

        print("receive audio")
        pass


if __name__ == "__main__":
    main()
