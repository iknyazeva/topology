from scipy.stats import *
import numpy as np


def poisson_homogeneous_point_process(rate, dx, dy=None, logging_on=True, point_num=None):
    """
    Реализация пуассоновского однородного точечного процесса в прямоугольной области.
    :param point_num: явно указать количество создаваемых точек
    :param logging_on: текстовый вывод
    :param rate: интенсивность процесса (среднее количество точек на единицу площади)
    :param dx: длина прямоугольника
    :param dy: ширина прямоугольника (по умолчанию равна длине)
    :return: список точек из R^2
    """
    if dy is None:
        dy = dx
    if point_num is None:
        point_num = poisson(rate * dx * dy).rvs()
    x = uniform.rvs(0, dx, (point_num, 1))
    y = uniform.rvs(0, dy, (point_num, 1))
    out = np.hstack((x, y))

    if logging_on:
        print("{0} Poisson distributed points generated".format(point_num))

    return out
